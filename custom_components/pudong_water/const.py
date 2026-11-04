"""常量。"""

DOMAIN = "pudong_water"
MANUFACTURER = "浦东威立雅"

CONF_CID = "cid"
CONF_SCAN_INTERVAL_DAYS = "scan_interval_days"

DEFAULT_SCAN_INTERVAL_DAYS = 15
MIN_SCAN_INTERVAL_DAYS = 1
MAX_SCAN_INTERVAL_DAYS = 30

STORAGE_VERSION = 1
# 长期统计的写法版本；缓存里的版本比它小就清掉重写
STATS_SCHEMA = 1
