import time
from datetime import datetime, timedelta

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from app.core.event import eventmanager, Event
from app.core.config import settings
from app.helper.mediaserver import MediaServerHelper
from app.plugins import _PluginBase
from typing import Any, List, Dict, Tuple, Optional
from app.log import logger
from app.schemas.types import EventType, NotificationType


class RefreshRecentMeta(_PluginBase):
    # 插件名称
    plugin_name = "刷新剧集元数据"
    # 插件描述
    plugin_desc = "定时通知媒体库刷新最近发布剧集元数据"
    # 插件图标
    plugin_icon = "backup.png"
    # 插件版本
    plugin_version = "1.1"
    # 插件作者
    plugin_author = "dandkong"
    # 作者主页
    author_url = "https://github.com/dandkong"
    # 插件配置项ID前缀
    plugin_config_prefix = "refreshrecentmeta_"
    # 加载顺序
    plugin_order = 99
    # 可使用的用户级别
    auth_level = 1

    # 私有属性
    _enabled = False
    # 任务执行间隔
    _cron = None
    _offset_days = "0"
    _onlyonce = False
    _notify = False
    # 私有属性
    mediaserver_helper = None

    # 定时器
    _scheduler: Optional[BackgroundScheduler] = None

    def init_plugin(self, config: dict = None):
        # 停止现有任务
        self.stop_service()
        self.mediaserver_helper = MediaServerHelper()
        if config:
            self._enabled = config.get("enabled")
            self._cron = config.get("cron")
            self._offset_days = config.get("offset_days")
            self._notify = config.get("notify")
            self._onlyonce = config.get("onlyonce")

            # 加载模块
        if self._enabled:
            # 定时服务
            self._scheduler = BackgroundScheduler(timezone=settings.TZ)

            if self._cron:
                try:
                    self._scheduler.add_job(
                        func=self.refresh_recent,
                        trigger=CronTrigger.from_crontab(self._cron),
                        name="刷新剧集元数据",
                    )
                except Exception as err:
                    logger.error(f"定时任务配置错误：{str(err)}")

            if self._onlyonce:
                logger.info(f"刷新最近剧集元数据服务启动，立即运行一次")
                self._scheduler.add_job(
                    func=self.refresh_recent,
                    trigger="date",
                    run_date=datetime.now(tz=pytz.timezone(settings.TZ))
                             + timedelta(seconds=3),
                    name="刷新剧集元数据",
                )
                # 关闭一次性开关
                self._onlyonce = False
                self.update_config(
                    {
                        "onlyonce": False,
                        "cron": self._cron,
                        "enabled": self._enabled,
                        "offset_days": self._offset_days,
                        "notify": self._notify,
                    }
                )

            # 启动任务
            if self._scheduler.get_jobs():
                self._scheduler.print_jobs()
                self._scheduler.start()

    def __get_date(self, offset_day):
        now_time = datetime.now()
        end_time = now_time + timedelta(days=offset_day)
        end_date = end_time.strftime("%Y-%m-%d")
        return end_date

    @eventmanager.register(EventType.PluginAction)
    def refresh_recent(self, event: Event = None):
        if event:
            event_data = event.event_data
            if not event_data or event_data.get("action") != "refreshrecentmeta":
                return

        logger.info(
            f"当前时间 {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time()))} 刷新剧集元数据"
        )
        success = self.__refresh_emby()
        # 发送通知
        if self._notify:
            if success:
                self.post_message(
                    mtype=NotificationType.SiteMessage,
                    title=f"【刷新最近{self._offset_days}天剧集元数据】",
                    text="刷新成功",
                )
            else:
                self.post_message(
                    mtype=NotificationType.SiteMessage,
                    title=f"【刷新最近{self._offset_days}天剧集元数据】",
                    text="刷新失败，请查看日志",
                )

    def __refresh_emby(self) -> bool:
        end_date = self.__get_date(-int(self._offset_days))
        url_end_date = f"[HOST]emby/Items?IncludeItemTypes=Episode&MinPremiereDate={end_date}&IsMissing=false&Recursive=true&api_key=[APIKEY]"
        # 有些没有日期的，也做个保底刷新
        url_start_date = f"[HOST]emby/Items?IncludeItemTypes=Episode&MaxPremiereDate=1900-01-01&IsMissing=false&Recursive=true&api_key=[APIKEY]"
        services = self.mediaserver_helper.get_services(name_filters=["Emby"])
        success = True
        for service_name, service in services:
            success = success and self._refresh_by_url(url_end_date, service) and self._refresh_by_url(url_start_date,
                                                                                                       service)
        return success

    def _refresh_by_url(self, url, service):
        res_g = service.get_data(url)
        success = False
        if res_g:
            success = True
            res_items = res_g.json().get("Items")
            if res_items:
                for res_item in res_items:
                    item_id = res_item.get("Id")
                    series_name = res_item.get("SeriesName")
                    name = res_item.get("Name")
                    # 刷新元数据
                    req_url = f"[HOST]emby/Items/{item_id}/Refresh?MetadataRefreshMode=FullRefresh&ImageRefreshMode=FullRefresh&ReplaceAllMetadata=true&ReplaceAllImages=true&api_key=[APIKEY]"
                    res_pos = service.post_data(req_url)
                    if res_pos:
                        logger.info(f"刷新元数据：{series_name} - {name}")
                    else:
                        logger.error(f"刷新媒体库对象 {item_id} 失败，无法连接Emby！")
        return success

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        """
        定义远程控制命令
        :return: 命令关键字、事件、描述、附带数据
        """
        return [
            {
                "cmd": "/refreshrecentmeta",
                "event": EventType.PluginAction,
                "desc": "刷新最近元数据",
                "category": "",
                "data": {"action": "refreshrecentmeta"},
            }
        ]

    def get_api(self) -> List[Dict[str, Any]]:
        pass

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        拼装插件配置页面，需要返回两块数据：1、页面配置；2、数据结构
        """
        return [
            {
                "component": "VForm",
                "content": [
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "enabled",
                                            "label": "启用插件",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "notify",
                                            "label": "开启通知",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "onlyonce",
                                            "label": "立即运行一次",
                                        },
                                    }
                                ],
                            },
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {"model": "cron", "label": "执行周期"},
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "offset_days",
                                            "label": "几天内",
                                        },
                                    }
                                ],
                            },
                        ],
                    },
                ],
            }
        ], {"enabled": False, "request_method": "POST", "webhook_url": ""}

    def get_page(self) -> List[dict]:
        pass

    def stop_service(self):
        """
        退出插件
        """
        try:
            if self._scheduler:
                self._scheduler.remove_all_jobs()
                if self._scheduler.running:
                    self._scheduler.shutdown()
                self._scheduler = None
        except Exception as e:
            logger.error("退出插件失败：%s" % str(e))
