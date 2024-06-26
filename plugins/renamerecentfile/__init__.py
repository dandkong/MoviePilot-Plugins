from app.chain import transfer
from app.core.metainfo import MetaInfoPath
import time
from datetime import datetime, timedelta

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from pathlib import Path
from app.core.event import eventmanager, Event
from app.chain.tmdb import TmdbChain
from app.core.config import settings
from app.plugins import _PluginBase
from typing import Any, List, Dict, Tuple, Optional
from app.log import logger
from app.schemas.types import EventType
from app.schemas import NotificationType, TransferInfo
from app.schemas.types import MediaType
from app.core.context import MediaInfo

from app.modules.emby import Emby
from app.modules.jellyfin import Jellyfin
from app.modules.plex import Plex


class RenameRecentFile(_PluginBase):
    # 插件名称
    plugin_name = "重命名剧集文件"
    # 插件描述
    plugin_desc = "定时重命名最近发布剧集文件名"
    # 插件图标
    plugin_icon = "backup.png"
    # 插件版本
    plugin_version = "1.0"
    # 插件作者
    plugin_author = "dandkong"
    # 作者主页
    author_url = "https://github.com/dandkong"
    # 插件配置项ID前缀
    plugin_config_prefix = "renamerecentfile_"
    # 加载顺序
    plugin_order = 98
    # 可使用的用户级别
    auth_level = 1

    # 私有属性
    _enabled = False
    # 任务执行间隔
    _cron = None
    _offset_days = "0"
    _onlyonce = False
    _notify = False
    _library_path = None

    # 定时器
    _scheduler: Optional[BackgroundScheduler] = None

    def init_plugin(self, config: dict = None):
        # 停止现有任务
        self.stop_service()
        self.tmdbchain = TmdbChain()
        if config:
            self._enabled = config.get("enabled")
            self._cron = config.get("cron")
            self._offset_days = config.get("offset_days")
            self._notify = config.get("notify")
            self._onlyonce = config.get("onlyonce")
            self._library_path = config.get("library_path")

            # 加载模块
        if self._enabled:
            # 定时服务
            self._scheduler = BackgroundScheduler(timezone=settings.TZ)

            if self._cron:
                try:
                    self._scheduler.add_job(
                        func=self.refresh_recent,
                        trigger=CronTrigger.from_crontab(self._cron),
                        name="重命名剧集文件",
                    )
                except Exception as err:
                    logger.error(f"定时任务配置错误：{str(err)}")

            if self._onlyonce:
                logger.info(f"重命名剧集文件服务启动，立即运行一次")
                self._scheduler.add_job(
                    func=self.refresh_recent,
                    trigger="date",
                    run_date=datetime.now(tz=pytz.timezone(settings.TZ))
                    + timedelta(seconds=3),
                    name="重命名剧集文件",
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
                        "library_path": self._library_path,
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
            if not event_data or event_data.get("action") != "renamerecentfile":
                return

        logger.info(
            f"当前时间 {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time()))} 重命名剧集文件"
        )
        # Emby
        if "emby" in settings.MEDIASERVER:
            self.__rename_by_emby()
        # Jeyllyfin
        if "jellyfin" in settings.MEDIASERVER:
            logger.error("暂不支持jellyfin")
        # Plex
        if "plex" in settings.MEDIASERVER:
            logger.error("暂不支持plex")

        # 发送通知
        if self._notify:
            self.post_message(
                mtype=NotificationType.SiteMessage,
                title=f"【重命名最近{self._offset_days}天剧集文件】",
                text="执行成功",
            )

    def __rename_by_emby(self):
        end_date = self.__get_date(-int(self._offset_days))
        # 获得_offset_day加入的剧集
        req_url = f"[HOST]emby/Items?IncludeItemTypes=Episode&MinPremiereDate={end_date}&Fields=Path&IsMissing=false&Recursive=true&api_key=[APIKEY]"
        res = Emby().get_data(req_url)
        if res:
            res_items = res.json().get("Items")
            if res_items:
                for res_item in res_items:
                    path = res_item.get("Path")
                    self.__rename(path)
        # 保底，有些剧集没有发布日期
        req_url = f"[HOST]emby/Items?IncludeItemTypes=Episode&MaxPremiereDate=1900-01-01&Fields=Path&IsMissing=false&Recursive=true&api_key=[APIKEY]"
        res = Emby().get_data(req_url)
        if res:
            res_items = res.json().get("Items")
            if res_items:
                for res_item in res_items:
                    path = res_item.get("Path")
                    self.__rename(path)    


    def __rename(self, media_path: str):
        logger.info(f"尝试更新文件名：{media_path}")

        # 处理路径映射 (处理同一媒体多分辨率的情况)
        if self._library_path:
            paths = self._library_path.split("\n")
            for path in paths:
                sub_paths = path.split(":")
                if len(sub_paths) < 2:
                    continue
                media_path = media_path.replace(sub_paths[0], sub_paths[1]).replace(
                    "\\", "/"
                )

        file_path = Path(media_path)

        logger.info(f"尝试更新moviepilot文件名：{media_path}")

        file_meta = MetaInfoPath(file_path)
        # 识别媒体信息
        mediainfo: MediaInfo = self.chain.recognize_media(meta=file_meta)

        # 获取集数据
        if mediainfo.type == MediaType.TV:
            episodes_info = self.tmdbchain.tmdb_episodes(
                tmdbid=mediainfo.tmdb_id, season=file_meta.begin_season or 1
            )
        else:
            episodes_info = None

        # 转移
        transferinfo: TransferInfo = self.chain.transfer(
            mediainfo=mediainfo,
            path=file_path,
            transfer_type="move",
            meta=file_meta,
            episodes_info=episodes_info,
        )
        if not transferinfo:
            logger.error("文件转移模块运行失败")
            return False
        return True

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
                "cmd": "/renamerecentfile",
                "event": EventType.PluginAction,
                "desc": "重命名最近文件",
                "category": "",
                "data": {"action": "renamerecentfile"},
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
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {
                                    "cols": 12,
                                },
                                "content": [
                                    {
                                        "component": "VTextarea",
                                        "props": {
                                            "model": "library_path",
                                            "rows": "2",
                                            "label": "媒体库路径映射",
                                            "placeholder": "媒体服务器路径:MoviePilot路径（一行一个）",
                                        },
                                    }
                                ],
                            }
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
