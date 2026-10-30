import json
from datetime import datetime, timedelta
from typing import Any, List, Dict, Tuple, Optional
import pytz
import requests
from urllib.parse import urlparse

from app.core.config import settings
from app.db.site_oper import SiteOper
from app.plugins import _PluginBase
from app.log import logger
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger


class CookieCloudToMP(_PluginBase):
    # 插件基础信息（和样板格式保持一致）
    plugin_name = "CookieCloud拉取同步站点Cookie"
    plugin_desc = "从外部CookieCloud服务器拉取Cookie，对比expires，自动更新MoviePilot站点Cookie"
    plugin_icon = "Cookiecloud_A.png"
    plugin_version = "1.0"
    plugin_author = "custom"
    author_url = ""
    plugin_config_prefix = "cookiecloudtmp_"
    plugin_order = 99
    auth_level = 1

    # 私有变量
    _enabled: bool = False
    _onlyonce: bool = False
    _cron: str = ""
    _cc_url: str = ""
    _cc_uuid: str = ""
    _cc_pwd: str = ""
    _scheduler: Optional[BackgroundScheduler] = None
    _siteoper = SiteOper()

    def init_plugin(self, config: dict = None):
        self.stop_service()
        if config:
            self._enabled = config.get("enabled")
            self._onlyonce = config.get("onlyonce")
            self._cron = config.get("cron")
            self._cc_url = config.get("cc_url", "").strip()
            self._cc_uuid = config.get("cc_uuid", "").strip()
            self._cc_pwd = config.get("cc_pwd", "").strip()

            if self._enabled or self._onlyonce:
                self._scheduler = BackgroundScheduler(timezone=settings.TZ)
                if self._onlyonce:
                    logger.info("CookieCloud拉取同步：立即执行一次")
                    self._scheduler.add_job(self.__sync_from_cc, 'date',
                                            run_date=datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(seconds=3),
                                            name="CC拉取Cookie")
                    self._onlyonce = False
                    self.__update_config()
                if self._cron:
                    try:
                        self._scheduler.add_job(func=self.__sync_from_cc,
                                                trigger=CronTrigger.from_crontab(self._cron),
                                                name="CC拉取Cookie")
                    except Exception as err:
                        logger.error(f"定时表达式错误：{err}")
                        self.systemmessage.put(f"执行周期配置错误：{err}")
                if self._scheduler.get_jobs():
                    self._scheduler.start()

    def __sync_from_cc(self):
        """从CookieCloud拉取，对比过期时间，更新站点Cookie"""
        if not all([self._cc_url, self._cc_uuid, self._cc_pwd]):
            logger.error("CookieCloud地址、UUID、密码不能为空！")
            return
        try:
            resp = requests.get(f"{self._cc_url.rstrip('/')}/api/get", params={
                "uuid": self._cc_uuid,
                "privateKey": self._cc_pwd
            }, timeout=15)
            resp.raise_for_status()
            ret = resp.json()
            if not ret.get("success"):
                logger.error(f"CookieCloud返回失败：{ret}")
                return
            cc_data = ret.get("data", {})
            cookie_data = cc_data.get("cookie_data", {})
        except Exception as e:
            logger.error(f"请求CookieCloud异常：{str(e)}")
            return

        # 遍历CC里的每个域名
        for domain, ck_list in cookie_data.items():
            if not ck_list:
                continue
            # 找出该域名对应的MP站点
            site = self._siteoper.get_by_domain(domain)
            if not site:
                logger.warning(f"MP内不存在站点：{domain}，跳过")
                continue
            # 取CC里cookie最大过期时间
            cc_exp = 0
            for ck in ck_list:
                exp = ck.get("expires", 0)
                if isinstance(exp, (int, float)) and exp > cc_exp:
                    cc_exp = exp
            # 读取现有站点cookie的最大过期时间
            mp_exp = 0
            if site.cookie:
                try:
                    old_cookies = json.loads(site.cookie)
                    for ck in old_cookies:
                        exp = ck.get("expires", 0)
                        if isinstance(exp, (int, float)) and exp > mp_exp:
                            mp_exp = exp
                except Exception:
                    pass
            # CC更新，才写入
            if cc_exp > mp_exp:
                self._siteoper.update_cookie(site.id, json.dumps(ck_list, ensure_ascii=False))
                logger.info(f"【{domain}】Cookie已更新，新过期时间：{cc_exp}")
            else:
                logger.info(f"【{domain}】Cookie无需更新，CC过期时间不优于本地")
        logger.info("CookieCloud同步任务执行完毕")

    def __update_config(self):
        self.update_config({
            "enabled": self._enabled,
            "onlyonce": self._onlyonce,
            "cron": self._cron,
            "cc_url": self._cc_url,
            "cc_uuid": self._cc_uuid,
            "cc_pwd": self._cc_pwd
        })

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        return []

    def get_api(self) -> List[Dict[str, Any]]:
        return []

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """配置表单页面"""
        return [
            {
                'component': 'VForm',
                'content': [
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 6},
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {'model': 'enabled', 'label': '启用插件'}
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 6},
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {'model': 'onlyonce', 'label': '立即运行一次'}
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12},
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {'model': 'cc_url', 'label': 'CookieCloud地址',
                                                  'placeholder': 'http://192.168.x.x:8088'}
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md':6},
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {'model': 'cc_uuid', 'label': 'CookieCloud UUID'}
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md':6},
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {'model': 'cc_pwd', 'label': 'CookieCloud 密码'}
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12},
                                'content': [
                                    {
                                        'component': 'VCronField',
                                        'props': {'model': 'cron', 'label': '执行周期', 'placeholder': '5位cron'}
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12},
                                'content': [
                                    {
                                        'component': 'VAlert',
                                        'props': {'type': 'info', 'variant': 'tonal',
                                                  'text': '从外部CookieCloud拉取Cookie，对比expires，仅当新Cookie过期时间更晚才更新站点Cookie。'}
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ], {
            "enabled": False,
            "onlyonce": False,
            "cron": "0 */2 * * *",
            "cc_url": "",
            "cc_uuid": "",
            "cc_pwd": ""
        }

    def get_page(self) -> List[dict]:
        return []

    def stop_service(self):
        """停止定时任务"""
        try:
            if self._scheduler:
                self._scheduler.remove_all_jobs()
                if self._scheduler.running:
                    self._scheduler.shutdown()
                self._scheduler = None
        except Exception as e:
            logger.error("退出插件失败：%s" % str(e))


__all__ = ["CookieCloudToMP"]
