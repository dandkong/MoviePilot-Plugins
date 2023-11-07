import time
from datetime import datetime, timedelta

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.config import settings
from app.plugins import _PluginBase
from typing import Any, List, Dict, Tuple, Optional
from app.log import logger
from app.utils.http import RequestUtils


class RefreshRecentMeta(_PluginBase):
    # 插件名称
    plugin_name = "自动刷新最近加入媒体元数据"
    # 插件描述
    plugin_desc = "自动刷新最近加入媒体元数据"
    # 插件图标
    plugin_icon = "backup.png"
    # 主题色
    plugin_color = "#4FB647"
    # 插件版本
    plugin_version = "1.2"
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

    # 定时器
    _scheduler: Optional[BackgroundScheduler] = None

    def init_plugin(self, config: dict = None):
        # 停止现有任务
        self.stop_service()

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
                    self._scheduler.add_job(func=self.__refresh_recent,
                                            trigger=CronTrigger.from_crontab(self._cron),
                                            name="自动刷新最近加入媒体元数据")
                except Exception as err:
                    logger.error(f"定时任务配置错误：{str(err)}")

            if self._onlyonce:
                logger.info(f"自动刷新最近媒体元数据服务启动，立即运行一次")
                self._scheduler.add_job(func=self.__refresh_recent, trigger='date',
                                        run_date=datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(seconds=3),
                                        name="自动刷新最近加入媒体元数据")
                # 关闭一次性开关
                self._onlyonce = False
                self.update_config({
                    "onlyonce": False,
                    "cron": self._cron,
                    "enabled": self._enabled,
                    "offset_days": self._offset_days,
                    "notify": self._notify,
                })

            # 启动任务
            if self._scheduler.get_jobs():
                self._scheduler.print_jobs()
                self._scheduler.start()

    def __get_date(self, offset_day):
        now_time = datetime.now()
        end_time = now_time + timedelta(days=offset_day)
        end_date = end_time.strftime("%Y-%m-%d")
        return end_date

    def __refresh_recent(self):
        if "emby" not in settings.MEDIASERVER:
            return

        logger.info(
            f"当前时间 {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time()))} 自动刷新最近加入媒体元数据")

        host = settings.EMBY_HOST
        apikey = settings.EMBY_API_KEY
        if not host or not apikey:
            return None
        end_date = self.__get_date(-int(self._offset_days))
        # 获得_offset_day加入的剧集
        req_url = "%semby/Items?IncludeItemTypes=Episode&MinPremiereDate=%s&IsMissing=false&Recursive=true&api_key=%s" % (
            host, end_date, apikey)
        try:
            res = RequestUtils().get_res(req_url)
            if res:
                res_items = res.json().get("Items")
                if res_items:
                    for res_item in res_items:
                        item_id = res_item.get('Id')
                        series_name = res_item.get('SeriesName')
                        name = res_item.get('Name')
                        # 刷新元数据
                        req_url = "%semby/Items/%s/Refresh?MetadataRefreshMode=FullRefresh&ImageRefreshMode=FullRefresh&ReplaceAllMetadata=true&ReplaceAllImages=true&api_key=%s" % (
                            host, item_id, apikey)
                        try:
                            res = RequestUtils().post_res(req_url)
                            if res:
                                logger.info(f"刷新元数据：{series_name} - {name}")
                            else:
                                logger.error(f"刷新媒体库对象 {item_id} 失败，无法连接Emby！")
                        except Exception as e:
                            logger.error(f"连接Items/Id/Refresh出错：" + str(e))
        except Exception as e:
            logger.error(f"连接Items出错：" + str(e))

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        pass

    def get_api(self) -> List[Dict[str, Any]]:
        pass

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        拼装插件配置页面，需要返回两块数据：1、页面配置；2、数据结构
        """
        return [
            {
                'component': 'VForm',
                'content': [
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'enabled',
                                            'label': '启用插件',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'notify',
                                            'label': '开启通知',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'onlyonce',
                                            'label': '立即运行一次',
                                        }
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
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'cron',
                                            'label': '执行周期'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'offset_days',
                                            'label': '几天内'
                                        }
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
                                'props': {
                                    'cols': 12,
                                },
                                'content': [
                                    {
                                        'component': 'VAlert',
                                        'props': {
                                            'type': 'info',
                                            'variant': 'tonal',
                                            'text': '备份文件路径默认为本地映射的config/plugins/AutoBackup。'
                                        }
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ], {
            "enabled": False,
            "request_method": "POST",
            "webhook_url": ""
        }

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
