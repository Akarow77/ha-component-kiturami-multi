"""Constants for Kiturami IoT Multi Manager."""

from homeassistant.const import Platform

DOMAIN = "kiturami_multi"
TITLE = "귀뚜라미"
MODEL = "IoT 멀티 매니저"
PLATFORMS: list[Platform] = [Platform.CLIMATE]

KITURAMI_API_URL = "https://igis.krb.co.kr/api"
MAX_TEMP = 45
MIN_TEMP = 5
