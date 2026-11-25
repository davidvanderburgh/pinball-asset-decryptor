"""PAD-1587: the stand-in's server lets in only a trusted key: an unknown key and a password are refused."""
import socket
import paramiko

HOST = '192.168.77.50'


def attempt(label, fn):
    t = paramiko.Transport(socket.create_connection((HOST, 22), timeout=8))
    t.start_client(timeout=8)
    try:
        fn(t)
        print('VERDICT %-18s FAIL (let in)' % label)
    except paramiko.AuthenticationException as e:
        print('VERDICT %-18s PASS (refused: %s)' % (label, e.__class__.__name__))
    except paramiko.SSHException as e:
        print('VERDICT %-18s PASS (refused: %s)' % (label, e))
    finally:
        t.close()


attempt('unknown key', lambda t: t.auth_publickey('root', paramiko.Ed25519Key.generate()
                                                   if hasattr(paramiko.Ed25519Key, 'generate')
                                                   else paramiko.RSAKey.generate(2048)))
attempt('password', lambda t: t.auth_password('root', 'root'))
attempt('no auth', lambda t: t.auth_none('root'))
