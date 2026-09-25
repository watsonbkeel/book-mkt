"""Local admin login, no shared default password."""
import hashlib,hmac,secrets,time,json

def set_password(store,username,password):
    if not 3<=len(username)<=80 or not username.replace('_','').replace('-','').isalnum():raise ValueError('管理员名称只使用字母/数字/下划线')
    if len(password)<14 or len(password)>256:raise ValueError('管理员密码至少14字符')
    salt=secrets.token_bytes(16);digest=hashlib.scrypt(password.encode(),salt=salt,n=16384,r=8,p=1)
    store.set_state('admin',{'username':username,'salt':salt.hex(),'hash':digest.hex(),'version':secrets.token_hex(12)})

def authenticate(store,username,password,ip):
    now=time.time();count=store.one('SELECT COUNT(*) AS n FROM login_attempts WHERE ip=? AND created_at>?',(ip,now-900))['n']
    if count>=5:return False
    store.execute('INSERT INTO login_attempts(ip,created_at) VALUES(?,?)',(ip,now))
    info=store.state('admin')
    if not info or len(password)>256:return False
    expected=hashlib.scrypt(password.encode(),salt=bytes.fromhex(info['salt']),n=16384,r=8,p=1).hex()
    ok=hmac.compare_digest(expected,info['hash']) and hmac.compare_digest(username.encode(),info['username'].encode())
    if ok:store.execute('DELETE FROM login_attempts WHERE ip=?',(ip,))
    return ok
