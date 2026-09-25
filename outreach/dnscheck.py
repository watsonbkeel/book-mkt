"""Bounded DNS-only check. No recipient probing or SMTP VRFY. MX existence is not delivery."""
from __future__ import annotations
import time,ipaddress
import dns.resolver
import dns.exception

class MXChecker:
    def __init__(self,resolver=None):
        self.resolver=resolver or dns.resolver.Resolver()
        self.cache={}
    def check(self,domain):
        domain=domain.lower().rstrip('.')
        cached=self.cache.get(domain)
        if cached and time.time()-cached['checked_at']<3600:return dict(cached)
        result={'domain':domain,'status':'unknown','mx':[],'checked_at':time.time(),'note':'MX核验不证明邮箱存在、送达或联系许可。'}
        try:
            answer=self.resolver.resolve(domain,'MX',lifetime=5)
            records=[str(r.exchange).rstrip('.') for r in answer]
            if '' in records:result['status']='null_mx'
            elif not records:result['status']='no_mx'
            elif any(x in ('localhost',) or x.endswith(('.local','.localhost','.internal')) for x in records):result['status']='unsafe_mx'
            else:
                literals=[]
                for x in records:
                    try:literals.append(ipaddress.ip_address(x))
                    except ValueError:pass
                result['status']='unsafe_mx' if literals else 'mx'
                result['mx']=records[:10]
        except dns.resolver.NXDOMAIN:result['status']='nxdomain'
        except dns.resolver.NoAnswer:result['status']='no_mx'
        except (dns.exception.Timeout,TimeoutError):result['status']='timeout'
        except (dns.resolver.NoNameservers,dns.exception.DNSException,OSError):result['status']='dns_error'
        self.cache[domain]=result
        return dict(result)
