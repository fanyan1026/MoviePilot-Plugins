"""
CookieCloud 站点Cookie自动同步 V3 新版（无基类，适配 jxxghp v3 latest）
"""
import time
from typing import List, Dict, Optional
import requests
from pydantic import BaseModel, Field


class CookieCloudSyncConfig(BaseModel):
    cookiecloud_url: str = Field(
        default="http://127.0.0.1:8088",
        title="CookieCloud服务地址",
        description="示例 http://192.168.1.100:8088，末尾不要斜杠"
    )
    cookiecloud_uuid: str = Field(default="", title="CookieCloud UUID")
    cookiecloud_key: str = Field(default="", title="CookieCloud 私钥")
    sync_interval: int = Field(
        default=30,
        title="自动同步间隔(分钟)",
        description="最小5分钟，低于5自动按5分钟执行"
    )
    site_domains: str = Field(
        default="",
        title="待同步域名列表",
        description="多个域名英文逗号分隔，例：hdtime.org,ultrahd.net,ahdbits.org"
    )


class CookieCloudSync:
    # 【必填标识属性，loader靠这些识别】
    plugin_name = "CookieCloud 站点Cookie自动同步"
    plugin_desc = "定时拉取CookieCloud，对比expires时间，自动更新MoviePilot站点Cookie，支持手动一键同步"
    plugin_version = "1.5.0"
    plugin_author = "custom"
    plugin_config_class = CookieCloudSyncConfig
    plugin_page_actions = [
        {"action": "manual_sync", "name": "立即同步", "description": "手动触发一次CookieCloud同步"}
    ]

    def __init__(self):
        self._last_run_time = 0
        # 配置读取：self.config 自动注入，新版框架内置
        self._site_manager = None

    def get_cookiecloud_data(self) -> Optional[Dict]:
        cfg = self.config
        base_url = cfg.cookiecloud_url.rstrip("/")
        url = f"{base_url}/api/get"
        params = {"uuid": cfg.cookiecloud_uuid, "privateKey": cfg.cookiecloud_key}
        try:
            resp = requests.get(url, params=params, timeout=15)
            resp.raise_for_status()
            ret = resp.json()
            if ret.get("success") is True:
                return ret.get("data", {})
            print(f"CookieCloud接口返回失败 {ret}")
            return None
        except Exception as e:
            print(f"请求CookieCloud异常 {str(e)}")
            return None

    @staticmethod
    def get_domain_cookies(cc_data: Dict, target_domain: str) -> Optional[List[Dict]]:
        cookie_groups = cc_data.get("cookie_data", [])
        for g in cookie_groups:
            if g.get("domain") == target_domain:
                return g.get("cookies", [])
        return None

    @staticmethod
    def max_expire_ts(cookies: List[Dict]) -> int:
        ts_list = []
        for c in cookies:
            exp = c.get("expires")
            if isinstance(exp, (int, float)) and exp > 0:
                ts_list.append(int(exp))
        return max(ts_list) if ts_list else 0

    def sync_one_domain(self, domain: str, cc_data: Dict):
        cc_cookies = self.get_domain_cookies(cc_data, domain)
        if cc_cookies is None:
            print(f"[{domain}] CookieCloud未找到该域名记录，跳过")
            return
        if not cc_cookies:
            print(f"[{domain}] CookieCloud存在域名，但cookie为空，跳过")
            return

        cc_exp = self.max_expire_ts(cc_cookies)
        if cc_exp <= 0:
            print(f"[{domain}] CookieCloud cookie无有效expires，无法判断新旧，跳过")
            return

        # 站点查询，新版SDK获取站点
        site = self.site_manager.get_site_by_domain(domain)
        if not site:
            print(f"[{domain}] MoviePilot内不存在该站点，跳过")
            return

        mp_exp = self.max_expire_ts(site.cookies or [])
        if cc_exp > mp_exp:
            print(f"[{domain}] CC更新(CC:{cc_exp} > MP:{mp_exp})，更新站点Cookie")
            self.site_manager.update_site_cookies(site_id=site.id, cookies=cc_cookies)
            print(f"[{domain}] Cookie更新完成")
        else:
            print(f"[{domain}] MP Cookie已是最新，无需更新(CC:{cc_exp} <= MP:{mp_exp})")

    def run_sync_job(self):
        cfg = self.config
        if not cfg.cookiecloud_url or not cfg.cookiecloud_uuid or not cfg.cookiecloud_key:
            print("CookieCloud配置缺失，请填写地址、UUID、私钥")
            return
        raw_domains = cfg.site_domains.strip()
        if not raw_domains:
            print("未配置待同步域名列表")
            return
        domains = [d.strip() for d in raw_domains.split(",") if d.strip()]
        print(f"===== CookieCloud同步开始，目标域名 {domains} =====")
        cc_data = self.get_cookiecloud_data()
        if not cc_data:
            print("获取CookieCloud数据失败，本次同步终止")
            return
        for dom in domains:
            self.sync_one_domain(dom, cc_data)
        print("===== CookieCloud同步结束 =====\n")

    def handle_page_action(self, action: str, data: dict):
        if action == "manual_sync":
            print("收到【立即同步】按钮指令")
            self.run_sync_job()
            return {"msg": "同步执行完毕，请查看系统日志", "success": True}
        return {"msg": "未知操作", "success": False}

    def plugin_run(self):
        cfg = self.config
        interval = max(5, cfg.sync_interval) * 60
        now_ts = time.time()
        if now_ts - self._last_run_time >= interval:
            self.run_sync_job()
            self._last_run_time = now_ts


# 必须导出，loader扫描顶层类
__all__ = ["CookieCloudSync"]
