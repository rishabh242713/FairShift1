import os, secrets, time
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP
from functools import wraps
from flask import Flask, request, session, jsonify, render_template, redirect, url_for, abort
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import create_engine, MetaData, Table, Column, Integer, String, Text, select, insert, update, and_, func

def now():
    return datetime.now(timezone.utc).replace(microsecond=0)

def stamp(dt=None):
    return (dt or now()).isoformat()

def pay_summary(shifts, rate):
    regular = overtime = 0
    for row in shifts:
        if not row['end']: continue
        minutes = max(0, int((datetime.fromisoformat(row['end'])-datetime.fromisoformat(row['start'])).total_seconds() // 60))
        regular += min(minutes, 480)
        overtime += max(0, minutes-480)
    base = int((Decimal(regular)*rate/60).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
    extra = int((Decimal(overtime)*rate*Decimal('1.5')/60).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
    return dict(regular_minutes=regular, overtime_minutes=overtime, base_paise=base, overtime_paise=extra, total_paise=base+extra)

def create_app(config=None):
    app = Flask(__name__)
    app.config.update(SECRET_KEY=os.getenv('SECRET_KEY') or secrets.token_hex(32), DATABASE_URL=os.getenv('DATABASE_URL','sqlite:///fairshift.db'), SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax', SESSION_COOKIE_SECURE=os.getenv('COOKIE_SECURE')=='1', MAX_CONTENT_LENGTH=16384, PERMANENT_SESSION_LIFETIME=timedelta(hours=8))
    if config: app.config.update(config)
    url = app.config['DATABASE_URL']
    if url.startswith('postgres://'): url = url.replace('postgres://', 'postgresql+psycopg://', 1)
    elif url.startswith('postgresql://'): url = url.replace('postgresql://', 'postgresql+psycopg://', 1)
    if url.startswith('sqlite'): engine = create_engine(url)
    else: engine = create_engine(url, pool_pre_ping=True, pool_size=1, max_overflow=0)
    meta=MetaData()
    users=Table('users',meta,Column('id',Integer,primary_key=True),Column('username',String(80),unique=True),Column('password',String(255)),Column('name',String(80)),Column('role',String(20)),Column('sector',String(40)),Column('rate',Integer))
    shifts=Table('shifts',meta,Column('id',Integer,primary_key=True),Column('user_id',Integer,index=True),Column('start',String(40)),Column('end',String(40)))
    reports=Table('reports',meta,Column('id',Integer,primary_key=True),Column('receipt',String(80),unique=True),Column('sector',String(40)),Column('kind',String(20)),Column('message',Text),Column('severity',String(20)),Column('status',String(30)),Column('day',String(10)))
    skills=Table('skills',meta,Column('id',Integer,primary_key=True),Column('user_id',Integer),Column('title',String(100)),Column('issuer',String(100)),Column('date',String(10)))
    meta.create_all(engine)
    app.extensions['db']=(engine,users,shifts,reports,skills)
    attempts={}
    def rows(conn,q): return [dict(r) for r in conn.execute(q).mappings()]
    def current():
        with engine.connect() as c:
            return c.execute(select(users).where(users.c.id==session.get('uid',-1))).mappings().first()
    def auth(role=None):
        def wrap(fn):
            @wraps(fn)
            def inner(*a,**kw):
                u=current()
                if not u: abort(401)
                if role and u['role']!=role: abort(403)
                return fn(u,*a,**kw)
            return inner
        return wrap
    @app.before_request
    def protect():
        if 'csrf' not in session: session['csrf']=secrets.token_hex(24)
        if request.method in ('POST','PUT','PATCH','DELETE'):
            token=request.headers.get('X-CSRF-Token') or request.form.get('csrf','')
            if not secrets.compare_digest(token,session['csrf']): abort(403)
    @app.after_request
    def headers(r):
        r.headers.update({'X-Content-Type-Options':'nosniff','X-Frame-Options':'DENY','Referrer-Policy':'no-referrer','Cache-Control':'no-store','Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'",'Permissions-Policy':'camera=(), geolocation=(), microphone=(self)'})
        return r
    @app.errorhandler(400)
    @app.errorhandler(401)
    @app.errorhandler(403)
    @app.errorhandler(404)
    @app.errorhandler(409)
    @app.errorhandler(429)
    def error(e): return jsonify(error={400:'Invalid input',401:'Please sign in',403:'Not permitted',404:'Not found',409:'Action conflicts with current state',429:'Too many attempts; wait 15 minutes'}[e.code]),e.code
    @app.get('/health')
    def health(): return {'status':'ok'}
    @app.route('/',methods=['GET','POST'])
    def login():
        if request.method=='GET':
            if current(): return redirect('/app')
            return render_template('login.html',csrf=session['csrf'],error=None)
        name=request.form.get('username','').strip().lower()[:80]
        key=(request.remote_addr,name)
        recent=[t for t in attempts.get(key,[]) if time.time()-t<900]
        if len(recent)>=10: abort(429)
        with engine.connect() as c: u=c.execute(select(users).where(users.c.username==name)).mappings().first()
        if not u or not check_password_hash(u['password'],request.form.get('password','')):
            attempts[key]=recent+[time.time()]
            return render_template('login.html',csrf=session['csrf'],error='Incorrect username or password.'),401
        attempts.pop(key,None); session.clear(); session['uid']=u['id']; session['csrf']=secrets.token_hex(24); session.permanent=True
        return redirect('/app')
    @app.post('/logout')
    def logout(): session.clear(); return redirect('/')
    @app.get('/app')
    @auth()
    def home(u): return render_template('app.html',user=u,csrf=session['csrf'])
    @app.get('/api/state')
    @auth()
    def state(u):
        with engine.connect() as c:
            if u['role']=='worker':
                ss=rows(c,select(shifts).where(shifts.c.user_id==u['id']).order_by(shifts.c.start.desc()))
                month=stamp()[:7]
                month_shifts=[s for s in ss if s['start'].startswith(month)]
                return jsonify(user=dict(name=u['name'],sector=u['sector'],rate=u['rate']),shifts=ss,pay=pay_summary(month_shifts,u['rate']),month=month,skills=rows(c,select(skills).where(skills.c.user_id==u['id'])),active=next((s for s in ss if not s['end']),None))
            team=rows(c,select(users.c.id,users.c.name,users.c.rate).where(and_(users.c.role=='worker',users.c.sector==u['sector'])))
            for worker in team:
                ss=rows(c,select(shifts).where(shifts.c.user_id==worker['id']).order_by(shifts.c.start.desc()))
                week=now()-timedelta(days=7)
                hours=sum(max(0,(datetime.fromisoformat(s['end']) if s['end'] else now()).timestamp()-max(datetime.fromisoformat(s['start']).timestamp(),week.timestamp()))/3600 for s in ss)
                rest=False
                if len(ss)>1 and ss[1]['end']: rest=(datetime.fromisoformat(ss[0]['start'])-datetime.fromisoformat(ss[1]['end'])).total_seconds()<11*3600
                active=next((s for s in ss if not s['end']),None)
                long=bool(active and (now()-datetime.fromisoformat(active['start'])).total_seconds()>12*3600)
                worker.update(hours=round(hours,1),active=bool(active),fatigue=hours>48 or rest or long,reason='Long active shift' if long else 'Short rest between shifts' if rest else 'Over 48 hours in 7 days' if hours>48 else 'No rule triggered')
            return jsonify(team=team,reports=rows(c,select(reports.c.id,reports.c.sector,reports.c.kind,reports.c.message,reports.c.severity,reports.c.status,reports.c.day).where(reports.c.sector==u['sector']).order_by(reports.c.id.desc())),sector=u['sector'])
    @app.post('/api/shift')
    @auth('worker')
    def shift(u):
        action=(request.get_json(silent=True) or {}).get('action')
        if action not in ('in','out'): abort(400)
        # Lock the worker row to serialize competing check-ins on PostgreSQL.
        with engine.begin() as c:
            c.execute(update(users).where(users.c.id==u['id']).values(rate=users.c.rate))
            active=c.execute(select(shifts).where(and_(shifts.c.user_id==u['id'],shifts.c.end==None))).mappings().first()
            if (action=='in' and active) or (action=='out' and not active): abort(409)
            if action=='in': c.execute(insert(shifts).values(user_id=u['id'],start=stamp()))
            else: c.execute(update(shifts).where(shifts.c.id==active['id']).values(end=stamp()))
        return {'ok':True}
    @app.post('/api/reports')
    @auth('worker')
    def report(u):
        d=request.get_json(silent=True) or {}; message=d.get('message',''); kind=d.get('kind'); severity=d.get('severity')
        if not isinstance(message,str) or not 5<=len(message.strip())<=1500 or kind not in ('hazard','feedback') or severity not in ('low','medium','high'): abort(400)
        receipt=secrets.token_urlsafe(24)
        with engine.begin() as c: c.execute(insert(reports).values(receipt=receipt,sector=u['sector'],kind=kind,message=message.strip(),severity=severity,status='Open',day=stamp()[:10]))
        return {'receipt':receipt},201
    @app.get('/api/receipt/<token>')
    @auth('worker')
    def receipt(u,token):
        with engine.connect() as c: r=c.execute(select(reports.c.kind,reports.c.status,reports.c.day).where(and_(reports.c.receipt==token,reports.c.sector==u['sector']))).mappings().first()
        if not r: abort(404)
        return dict(r)
    @app.post('/api/reports/<int:rid>/status')
    @auth('admin')
    def status(u,rid):
        status=(request.get_json(silent=True) or {}).get('status')
        if status not in ('Open','In progress','Resolved'): abort(400)
        with engine.begin() as c:
            result=c.execute(update(reports).where(and_(reports.c.id==rid,reports.c.sector==u['sector'])).values(status=status))
            if not result.rowcount: abort(404)
        return {'ok':True}
    @app.cli.command('seed')
    def seed_command():
        seed_demo(app); print('Demo accounts created. See README for credentials.')
    return app

def seed_demo(app):
    engine,users,shifts,reports,skills=app.extensions['db']
    with engine.begin() as c:
        if c.execute(select(func.count()).select_from(users)).scalar(): return
        for username,name,role,sector in [('worker.site','Arun Kumar','worker','Construction'),('admin.site','Meera Shah','admin','Construction'),('worker.campus','Priya Devi','worker','College'),('admin.campus','Ravi Menon','admin','College')]:
            uid=c.execute(insert(users).values(username=username,name=name,role=role,sector=sector,rate=12500,password=generate_password_hash('FairShift-demo-2026!'))).inserted_primary_key[0]
            if role=='worker':
                for days,hours in [(3,10),(2,9),(1,8)]:
                    start=(now()-timedelta(days=days)).replace(hour=7,minute=0,second=0)
                    c.execute(insert(shifts).values(user_id=uid,start=stamp(start),end=stamp(start+timedelta(hours=hours))))
                c.execute(insert(skills).values(user_id=uid,title='Site safety induction' if sector=='Construction' else 'Safe chemical handling',issuer='Demo training team',date=stamp()[:10]))
        for sector,msg in [('Construction','Loose handrail near the east staircase. Please inspect before the next shift.'),('College','Cleaning cupboard needs labelled gloves and a spill kit.')]:
            c.execute(insert(reports).values(receipt=secrets.token_urlsafe(24),sector=sector,kind='hazard',message=msg,severity='high',status='Open',day=stamp()[:10]))

if __name__=='__main__':
    create_app().run(host='0.0.0.0',port=int(os.getenv('PORT','8080')))
