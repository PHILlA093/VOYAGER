"""网络请求助手:使用系统代理失败(代理软件未开启)时,自动去掉代理直连重试一次。"""
import requests


def _is_proxy_error(e):
    name = type(e).__name__
    text = str(e)
    return (
        "ProxyError" in name
        or "Unable to connect to proxy" in text
        or ("proxy" in text.lower() and "connection" in text.lower())
    )


def request(method, url, **kwargs):
    """先按系统代理请求;若因代理未开启而失败,自动直连重试一次。"""
    for direct in (False, True):
        try:
            if direct:
                session = requests.Session()
                session.trust_env = False
                session.proxies = {}
                kwargs.pop("proxies", None)
                return session.request(method, url, **kwargs)
            return requests.request(method, url, **kwargs)
        except requests.RequestException as e:
            if not direct and _is_proxy_error(e):
                continue
            raise
