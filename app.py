import os, secrets, mimetypes
from datetime import timedelta
from functools import wraps
from pathlib import Path
from flask import Flask, render_template, request, redirect, url_for, session, flash, abort, send_file
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
import psycopg
from psycopg.rows import dict_row

load_dotenv()
app=Flask(__name__)
app.secret_key=os.getenv('SECRET_KEY') or secrets.token_hex(32)
app.config.update(PERMANENT_SESSION_LIFETIME=timedelta(days=30),SESSION_COOKIE_HTTPONLY=True,SESSION_COOKIE_SAMESITE='Lax',SESSION_COOKIE_SECURE=os.getenv('COOKIE_SECURE','false').lower()=='true',MAX_CONTENT_LENGTH=5*1024*1024)
UPLOAD=Path(os.getenv('UPLOAD_DIR',Path(__file__).parent/'uploads'))
UPLOAD.mkdir(parents=True,exist_ok=True)

def db():
    if not os.getenv('DATABASE_URL'): raise RuntimeError('Set DATABASE_URL in .env before starting')
    return psycopg.connect(os.environ['DATABASE_URL'],row_factory=dict_row)
def query(sql,args=(),one=False):
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(sql,args)
            return cur.fetchone() if one else cur.fetchall() if cur.description else None

def user():
    if not session.get('uid'): return None
    u=query('SELECT id,minecraft_username,email,role,banned,created_at FROM users WHERE id=%s',(session['uid'],),True)
    if not u or u['banned']:
        session.clear();return None
    return u
@app.context_processor
def ctx():
    try: settings={r['key']:r['value'] for r in query('SELECT key,value FROM settings')}
    except Exception: settings={}
    return {'me':user(),'settings':settings}
def login_required(fn):
    @wraps(fn)
    def wrap(*a,**kw):
        if not user(): flash('Please log in first.');return redirect(url_for('login'))
        return fn(*a,**kw)
    return wrap
def admin_required(fn):
    @wraps(fn)
    def wrap(*a,**kw):
        u=user()
        if not u or u['role']!='admin': abort(403)
        return fn(*a,**kw)
    return wrap
def csrf():
    if 'csrf' not in session: session['csrf']=secrets.token_urlsafe(32)
    return session['csrf']
app.jinja_env.globals['csrf']=csrf
@app.before_request
def check_csrf():
    if request.method in ('POST','PUT','PATCH','DELETE') and not secrets.compare_digest(request.form.get('csrf',''),session.get('csrf','')): abort(400,'Invalid CSRF token')
@app.after_request
def headers(r):
    r.headers['X-Content-Type-Options']='nosniff';r.headers['X-Frame-Options']='DENY';r.headers['Referrer-Policy']='strict-origin-when-cross-origin'
    return r
@app.route('/')
def home():
    return render_template('home.html',products=query('SELECT * FROM products WHERE active=true ORDER BY display_order,id'))
@app.route('/register',methods=['GET','POST'])
def register():
    if request.method=='POST':
        email=request.form.get('email','').strip().lower();name=request.form.get('minecraft_username','').strip();pw=request.form.get('password','')
        if not (3<=len(name)<=32 and '@' in email and len(pw)>=8): flash('Use a valid Minecraft username, email and password (8+ characters).')
        elif pw!=request.form.get('confirm'): flash('Passwords do not match.')
        else:
            try:
                row=query('INSERT INTO users(minecraft_username,email,password_hash) VALUES (%s,%s,%s) RETURNING id',(name,email,generate_password_hash(pw)),True)
                session.clear();session['uid']=row['id'];session.permanent=True;return redirect(url_for('dashboard'))
            except psycopg.errors.UniqueViolation: flash('Email is already registered.')
    return render_template('auth.html',mode='register')
@app.route('/login',methods=['GET','POST'])
def login():
    if request.method=='POST':
        row=query('SELECT * FROM users WHERE email=%s',(request.form.get('email','').lower().strip(),),True)
        if row and not row['banned'] and check_password_hash(row['password_hash'],request.form.get('password','')):
            session.clear();session['uid']=row['id'];session.permanent=True;return redirect(url_for('dashboard'))
        flash('Invalid credentials or account unavailable.')
    return render_template('auth.html',mode='login')
@app.post('/logout')
def logout(): session.clear();return redirect(url_for('home'))
@app.route('/dashboard')
@login_required
def dashboard():
    return render_template('dashboard.html',orders=query('SELECT * FROM orders WHERE user_id=%s ORDER BY created_at DESC',(session['uid'],)))
@app.route('/purchase/<int:pid>',methods=['GET','POST'])
@login_required
def purchase(pid):
    p=query('SELECT * FROM products WHERE id=%s AND active=true',(pid,),True)
    if not p: abort(404)
    if request.method=='POST':
        utr=request.form.get('utr','').strip()
        f=request.files.get('screenshot');filename=None
        if not (6<=len(utr)<=80): flash('Enter a valid UTR/reference number.');return render_template('purchase.html',p=p)
        if not f or not f.filename: flash('Upload a payment screenshot.');return render_template('purchase.html',p=p)
        import filetype

        raw = f.read()
        kind = filetype.guess_extension(raw)

        if kind == "jpg":
         kind = "jpeg"
        if kind not in ('jpeg','png','webp') or len(raw)>4*1024*1024: flash('Only PNG/JPEG/WebP images under 4 MB are allowed.');return render_template('purchase.html',p=p)
        filename=secrets.token_hex(18)+('.jpg' if kind=='jpeg' else '.'+kind)
        (UPLOAD/filename).write_bytes(raw)
        query('INSERT INTO orders(user_id,product_id,product_name,price,utr,screenshot_path) VALUES (%s,%s,%s,%s,%s,%s)',(session['uid'],p['id'],p['name'],p['price'],utr,filename))
        flash('Payment submitted! Awaiting manual verification.');return redirect(url_for('dashboard'))
    return render_template('purchase.html',p=p)
@app.post('/order/<int:oid>/edit')
@login_required
def edit_order(oid):
    order=query('SELECT * FROM orders WHERE id=%s AND user_id=%s',(oid,session['uid']),True)
    if not order: abort(404)
    if order['status']!='Pending': abort(403)
    utr=request.form.get('utr','').strip()
    if not 6<=len(utr)<=80: abort(400)
    query('UPDATE orders SET utr=%s WHERE id=%s AND user_id=%s AND status=%s',(utr,oid,session['uid'],'Pending'))
    flash('UTR updated.');return redirect(url_for('dashboard'))
@app.route('/receipt/<int:oid>')
@login_required
def receipt(oid):
    u=user();o=query('SELECT * FROM orders WHERE id=%s',(oid,),True)
    if not o or (o['user_id']!=u['id'] and u['role']!='admin') or not o['screenshot_path']:abort(404)
    return send_file(UPLOAD/o['screenshot_path'])
@app.route('/admin')
@admin_required
def admin():
    return render_template('admin.html',tab=request.args.get('tab','orders'),orders=query('SELECT o.*,u.minecraft_username,u.email FROM orders o JOIN users u ON u.id=o.user_id ORDER BY o.created_at DESC LIMIT 150'),products=query('SELECT * FROM products ORDER BY display_order,id'),users=query('SELECT id,minecraft_username,email,role,banned,created_at FROM users ORDER BY created_at DESC LIMIT 150'),stats=query("SELECT count(*) total,count(*) FILTER(WHERE status='Pending') pending,coalesce(sum(price) FILTER(WHERE status='Approved'),0) revenue FROM orders",one=True))
def audit(action,typ,tid):query('INSERT INTO audit_logs(admin_id,action,target_type,target_id) VALUES (%s,%s,%s,%s)',(session['uid'],action,typ,tid))
@app.post('/admin/order/<int:oid>')
@admin_required
def admin_order(oid):
    status=request.form.get('status');notes=request.form.get('notes','')[:1000]
    if status not in ('Pending','Approved','Rejected'):abort(400)
    query('UPDATE orders SET status=%s,admin_notes=%s,processed_by=%s,processed_at=now() WHERE id=%s',(status,notes,session['uid'],oid));audit('order_'+status,'order',oid)
    flash('Order updated.');return redirect(url_for('admin'))
@app.post('/admin/product')
@admin_required
def admin_product():
    pid=request.form.get('id');name=request.form.get('name','').strip()[:120];category=request.form.get('category','Ranks')[:60];desc=request.form.get('description','')[:500]
    try:price=int(request.form.get('price','-1'));ordr=int(request.form.get('display_order','0'))
    except ValueError:abort(400)
    if not name or price<0:abort(400)
    active=request.form.get('active')=='on'
    if pid:
        query('UPDATE products SET name=%s,category=%s,description=%s,price=%s,active=%s,display_order=%s WHERE id=%s',(name,category,desc,price,active,ordr,pid));audit('product_edit','product',int(pid))
    else:
        p=query('INSERT INTO products(name,category,description,price,active,display_order) VALUES (%s,%s,%s,%s,%s,%s) RETURNING id',(name,category,desc,price,active,ordr),True);audit('product_add','product',p['id'])
    flash('Product saved.');return redirect(url_for('admin',tab='products'))
@app.post('/admin/user/<int:uid>/ban')
@admin_required
def admin_ban(uid):
    if uid==session['uid']:abort(400)
    target=query('SELECT banned,role FROM users WHERE id=%s',(uid,),True)
    if not target or target['role']=='admin':abort(403)
    query('UPDATE users SET banned=%s WHERE id=%s',(not target['banned'],uid));audit('user_ban_toggle','user',uid)
    return redirect(url_for('admin',tab='users'))
@app.post('/admin/settings')
@admin_required
def admin_settings():
    for k in ('server_ip','discord_url','upi_id'):
        v=request.form.get(k,'').strip()[:300]
        query('INSERT INTO settings(key,value) VALUES (%s,%s) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(k,v))
    flash('Settings updated.');return redirect(url_for('admin',tab='settings'))
@app.cli.command('init-db')
def init_db():
    with db() as conn:
        with conn.cursor() as c:c.execute((Path(__file__).parent/'schema.sql').read_text())
    print('Database initialized')
@app.cli.command('create-admin')
def create_admin():
    email=os.getenv('ADMIN_EMAIL','').strip().lower();pw=os.getenv('ADMIN_PASSWORD','')
    if not email or len(pw)<12:raise RuntimeError('Set ADMIN_EMAIL and ADMIN_PASSWORD (12+ chars)')
    query("INSERT INTO users(minecraft_username,email,password_hash,role) VALUES ('WindCrestOwner',%s,%s,'admin') ON CONFLICT(email) DO UPDATE SET password_hash=excluded.password_hash,role='admin'",(email,generate_password_hash(pw)))
    print('Admin account created/updated')
if __name__=='__main__':app.run(debug=False)
