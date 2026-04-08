from datetime import datetime
import enum
import json
import logging
import random
import re
import string
import pandas as pd
from websocket import create_connection
import requests

logger = logging.getLogger(__name__)


class Interval(enum.Enum):
    in_1_minute = "1"
    in_3_minute = "3"
    in_5_minute = "5"
    in_15_minute = "15"
    in_30_minute = "30"
    in_45_minute = "45"
    in_1_hour = "1H"
    in_2_hour = "2H"
    in_3_hour = "3H"
    in_4_hour = "4H"
    in_daily = "1D"
    in_weekly = "1W"
    in_monthly = "1M"


class TvDatafeed:
    __search_url = 'https://symbol-search.tradingview.com/symbol_search/?text={}&hl=1&exchange={}&lang=en&type=&domain=production'
    __ws_headers = json.dumps({"Origin": "https://data.tradingview.com"})
    __ws_timeout = 20

    def __init__(
        self,
        username: str = None,
        password: str = None,
        sessionid: str = None,
        sessionid_sign: str = None,
        auth_token: str = None,
        sessionid_exp: str = None,
        auth_token_exp: str = None,
        auth = None,
    ) -> None:
        """Create TvDatafeed object

        Args:
            username (str, optional): tradingview username. Defaults to None.
            password (str, optional): tradingview password. Defaults to None.
            sessionid (str, optional): tradingview sessionid cookie. Defaults to None.
            sessionid_sign (str, optional): tradingview sessionid_sign cookie. Defaults to None.
            auth_token (str, optional): tradingview auth token (JWT). Defaults to None.
            sessionid_exp (str, optional): sessionid expires at (ISO format). Defaults to None.
            auth_token_exp (str, optional): auth_token expires at (ISO format). Defaults to None.
            auth (Auth, optional): Auth object. Defaults to None.
        """

        from .auth import Auth, UserAccount, UserCookie, UserAuthToken

        self.ws_debug = False
        self.auth = None
        self._auth_error = None

        # 첫 번째 positional argument가 Auth 객체인 경우
        if isinstance(username, Auth):
            auth = username
            username = None

        # 개별 필드로 Auth 객체 구성
        if auth is None:
            account = UserAccount(uid=username, pw=password) if username and password else None

            cookie = None
            if sessionid and sessionid_sign:
                expires_at = None
                if sessionid_exp:
                    try:
                        expires_at = datetime.fromisoformat(sessionid_exp)
                    except (ValueError, TypeError):
                        logger.warning(f"sessionid_exp 파싱 실패: {sessionid_exp}")
                cookie = UserCookie(sessionid=sessionid, sessionid_sign=sessionid_sign, expires_at=expires_at)

            user_token = None
            if auth_token:
                expires_at = None
                if auth_token_exp:
                    try:
                        expires_at = datetime.fromisoformat(auth_token_exp)
                    except (ValueError, TypeError):
                        logger.warning(f"auth_token_exp 파싱 실패: {auth_token_exp}")
                user_token = UserAuthToken(auth_token=auth_token, expires_at=expires_at)

            auth = Auth(account=account, cookie=cookie, auth_token=user_token)

        self.token = self.__auth(auth)

        if self.token is None:
            self.token = "unauthorized_user_token"
            if self._auth_error is None:
                self._auth_error = "no credentials provided"
            logger.warning(
                "you are using nologin method, data you access may be limited"
            )

        self.ws = None
        self._ws_connected = False
        self.session = None
        self.chart_session = None

    def __try_login(self, account):
        """tradingview_login 호출 공통 로직. RateLimitError는 caller에게 전파."""
        from .auth import tradingview_login

        if not account:
            self._auth_error = "no credentials for login"
            return None
        auth_result, login_err = tradingview_login(account)
        if auth_result:
            self.auth = auth_result
            return auth_result.get_token()
        self._auth_error = login_err or "login failed (unknown)"
        return None

    def __auth(self, auth):
        from .auth import refresh_auth_token, RateLimitError

        account = auth.account
        cookie = auth.cookie

        try:
            # 1. Cookie 검증
            if cookie and cookie.is_expired():
                logger.warning("sessionid expired")
                cookie = None

            if cookie is None:
                return self.__try_login(account)

            # 2. Token 검증 (cookie는 유효한 상태)
            if auth.auth_token and not auth.auth_token.is_expired():
                logger.info("cached auth_token is valid")
                self.auth = auth
                return auth.get_token()
            if auth.auth_token:
                logger.info("auth_token expired")

            # 3. Token 없거나 만료 → refresh
            self.auth = auth
            token = refresh_auth_token(self.auth)
            if token:
                logger.info("auth_token refreshed via /quote_token/")
                return token
            logger.warning("quote_token refresh failed")

            # 4. Refresh 실패 → login 시도
            if account:
                logger.info("refresh failed, attempting login")
                return self.__try_login(account)
            self._auth_error = "token refresh failed, no credentials for login"

        except RateLimitError as e:
            self._auth_error = f"rate limit: {e}"
            logger.error(f"rate limit 감지, 인증 중단: {e}")

        return None

    def get_errmsg(self) -> str:
        """인증 실패 시 상세 사유를 반환한다. 인증 성공 시 None."""
        return self._auth_error

    def __create_connection(self):
        logging.debug("creating websocket connection")
        if self.ws is not None:
            try:
                self.ws.close()
            except Exception:
                pass
        self.ws = create_connection(
            "wss://data.tradingview.com/socket.io/websocket", headers=self.__ws_headers, timeout=self.__ws_timeout
        )

    def is_connected(self):
        """웹소켓 연결 상태를 반환한다."""
        return self._ws_connected and self.ws is not None

    def connect(self):
        """웹소켓 연결을 생성한다."""
        self.__create_connection()
        self._ws_connected = True
        logger.debug("websocket connected")

    def disconnect(self):
        """웹소켓 연결을 종료한다. 활성 세션을 서버에서 삭제 후 연결을 닫는다."""
        if self.ws is not None:
            try:
                if self.session is not None:
                    self.__send_message("quote_delete_session", [self.session])
                    self.session = None
                if self.chart_session is not None:
                    self.__send_message("chart_delete_session", [self.chart_session])
                    self.chart_session = None
            except Exception:
                pass
            try:
                self.ws.close()
            except Exception:
                pass
            self.ws = None
        self.session = None
        self.chart_session = None
        self._ws_connected = False
        logger.debug("websocket disconnected")


    def reconnect(self):
        """웹소켓을 재연결한다."""
        logger.debug("websocket reconnecting")
        self.disconnect()
        self.connect()

    def keepalive(self, msg):
        """TradingView heartbeat(~h~) 메시지를 echo back한다.

        Returns: heartbeat이면 True, 아니면 False
        """
        if "~h~" not in msg:
            return False
        try:
            self.ws.send(msg)
        except Exception as e:
            logger.error(f"keepalive failed: {e}")
            self._ws_connected = False
        return True

    @staticmethod
    def __filter_raw_message(text):
        try:
            found = re.search('"m":"(.+?)",', text).group(1)
            found2 = re.search('"p":(.+?"}"])}', text).group(1)

            return found, found2
        except AttributeError:
            logger.error("error in filter_raw_message")

    @staticmethod
    def __generate_session(prefix="qs_"):
        return prefix + "".join(random.choice(string.ascii_lowercase) for _ in range(12))

    @staticmethod
    def __generate_chart_session():
        return TvDatafeed.__generate_session("cs_")

    @staticmethod
    def __prepend_header(st):
        return "~m~" + str(len(st)) + "~m~" + st

    @staticmethod
    def __construct_message(func, param_list):
        return json.dumps({"m": func, "p": param_list}, separators=(",", ":"))

    def __create_message(self, func, paramList):
        return self.__prepend_header(self.__construct_message(func, paramList))

    def __send_message(self, func, args):
        m = self.__create_message(func, args)
        if self.ws_debug:
            print(m)
        self.ws.send(m)

    @staticmethod
    def __create_df(raw_data, symbol):
        try:
            out = re.search(r'"s":\[(.+?)\}\]', raw_data).group(1)
            x = out.split(',{"')
            data = list()
            volume_data = True

            for xi in x:
                xi = re.split(r"\[|:|,|\]", xi)
                ts = datetime.fromtimestamp(float(xi[4]))

                row = [ts]

                for i in range(5, 10):

                    # skip converting volume data if does not exists
                    if not volume_data and i == 9:
                        row.append(0.0)
                        continue
                    try:
                        row.append(float(xi[i]))

                    except ValueError:
                        volume_data = False
                        row.append(0.0)
                        logger.debug('no volume data')

                data.append(row)

            data = pd.DataFrame(
                data, columns=["datetime", "open",
                               "high", "low", "close", "volume"]
            ).set_index("datetime")
            data.insert(0, "symbol", value=symbol)
            return data
        except AttributeError:
            logger.error("no data, please check the exchange and symbol")

    @staticmethod
    def __format_symbol(symbol, exchange, contract: int = None):

        if ":" in symbol:
            pass
        elif contract is None:
            symbol = f"{exchange}:{symbol}"

        elif isinstance(contract, int):
            symbol = f"{exchange}:{symbol}{contract}!"

        else:
            raise ValueError("not a valid contract")

        return symbol

    def get_hist(
        self,
        symbol: str,
        exchange: str = "NSE",
        interval: Interval = Interval.in_daily,
        n_bars: int = 10,
        fut_contract: int = None,
        extended_session: bool = False,
    ) -> pd.DataFrame:
        """get historical data

        Args:
            symbol (str): symbol name
            exchange (str, optional): exchange, not required if symbol is in format EXCHANGE:SYMBOL. Defaults to None.
            interval (str, optional): chart interval. Defaults to 'D'.
            n_bars (int, optional): no of bars to download, max 5000. Defaults to 10.
            fut_contract (int, optional): None for cash, 1 for continuous current contract in front, 2 for continuous next contract in front . Defaults to None.
            extended_session (bool, optional): regular session if False, extended session if True, Defaults to False.

        Returns:
            pd.Dataframe: dataframe with sohlcv as columns
        """
        symbol = self.__format_symbol(
            symbol=symbol, exchange=exchange, contract=fut_contract
        )

        interval = interval.value

        if not self.is_connected():
            self.connect()

        self.session = self.__generate_session()
        self.chart_session = self.__generate_chart_session()

        self.__send_message("set_auth_token", [self.token])
        self.__send_message("chart_create_session", [self.chart_session, ""])
        self.__send_message("quote_create_session", [self.session])
        self.__send_message(
            "quote_set_fields",
            [
                self.session,
                "ch",
                "chp",
                "current_session",
                "description",
                "local_description",
                "language",
                "exchange",
                "fractional",
                "is_tradable",
                "lp",
                "lp_time",
                "minmov",
                "minmove2",
                "original_name",
                "pricescale",
                "pro_name",
                "short_name",
                "type",
                "update_mode",
                "volume",
                "currency_code",
                "rchp",
                "rtc",
            ],
        )

        self.__send_message(
            "quote_add_symbols", [self.session, symbol,
                                  {"flags": ["force_permission"]}]
        )
        self.__send_message("quote_fast_symbols", [self.session, symbol])

        self.__send_message(
            "resolve_symbol",
            [
                self.chart_session,
                "symbol_1",
                '={"symbol":"'
                + symbol
                + '","adjustment":"splits","session":'
                + ('"regular"' if not extended_session else '"extended"')
                + "}",
            ],
        )
        self.__send_message(
            "create_series",
            [self.chart_session, "s1", "s1", "symbol_1", interval, n_bars],
        )
        self.__send_message("switch_timezone", [
                            self.chart_session, "exchange"])

        raw_data_parts = []

        logger.debug(f"getting data for {symbol}...")
        while True:
            try:
                result = self.ws.recv()
            except Exception as e:
                logger.error(e)
                self._ws_connected = False
                break
            if self.keepalive(result):
                continue
            if self.chart_session not in result:
                continue
            if "timescale_update" in result:
                raw_data_parts.append(result)
            if "series_completed" in result:
                break

        return self.__create_df("\n".join(raw_data_parts), symbol)

    __search_headers = {
        "Origin": "https://www.tradingview.com",
        "Referer": "https://www.tradingview.com/",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
        "Accept": "application/json",
    }

    def search_symbol(self, text: str, exchange: str = ''):
        url = self.__search_url.format(text, exchange)

        symbols_list = []
        try:
            resp = requests.get(url, headers=self.__search_headers, timeout=10)
            resp.raise_for_status()

            clean_text = re.sub(r"</?em>", "", resp.text)
            symbols_list = json.loads(clean_text)
        except Exception as e:
            logger.error(e)

        return symbols_list


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    tv = TvDatafeed()
    print(tv.get_hist("CRUDEOIL", "MCX", fut_contract=1))
    print(tv.get_hist("NIFTY", "NSE", fut_contract=1))
    print(
        tv.get_hist(
            "EICHERMOT",
            "NSE",
            interval=Interval.in_1_hour,
            n_bars=500,
            extended_session=False,
        )
    )
