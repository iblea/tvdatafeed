import json
import base64
import logging
from datetime import datetime, timedelta

import requests

logger = logging.getLogger(__name__)

SIGNIN_URL = "https://www.tradingview.com/accounts/signin/"
QUOTE_TOKEN_URL = "https://www.tradingview.com/quote_token/"

SIGNIN_HEADERS = {
    "Accept": "*/*",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
    "Origin": "https://www.tradingview.com",
    "Referer": "https://www.tradingview.com/",
    "X-Language": "en",
    "X-Requested-With": "XMLHttpRequest",
    "Sec-Ch-Ua": '"Not-A.Brand";v="24", "Chromium";v="146"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"macOS"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "same-origin",
    "Sec-Fetch-Site": "same-origin",
}


class RateLimitError(Exception):
    pass


class UserAccount:
    def __init__(self, uid: str, pw: str):
        self.uid = uid
        self.pw = pw

    def __repr__(self):
        return f"UserAccount(uid={self.uid})"


class UserCookie:
    def __init__(self, sessionid: str, sessionid_sign: str, expires_at: datetime = None):
        self.sessionid = sessionid
        self.sessionid_sign = sessionid_sign
        self.expires_at = expires_at

    def is_expired(self) -> bool:
        if self.expires_at is None:
            return True
        return datetime.now() >= self.expires_at

    def __repr__(self):
        return f"UserCookie(sessionid={self.sessionid[:8]}..., expires_at={self.expires_at})"


class UserAuthToken:
    def __init__(self, auth_token: str, expires_at: datetime = None):
        self.auth_token = auth_token
        self.expires_at = expires_at or self._parse_exp(auth_token)

    def _parse_exp(self, token: str) -> datetime:
        try:
            payload = token.split(".")[1]
            payload += "=" * (-len(payload) % 4)
            decoded = json.loads(base64.b64decode(payload))
            return datetime.fromtimestamp(decoded["exp"]) - timedelta(minutes=10)
        except Exception:
            logger.warning("JWT exp 파싱 실패, 만료로 처리")
            return datetime.now()

    def is_expired(self) -> bool:
        return datetime.now() >= self.expires_at

    def __repr__(self):
        return f"UserAuthToken(expires_at={self.expires_at}, expired={self.is_expired()})"


class Auth:
    def __init__(self, account: UserAccount = None, cookie: UserCookie = None, auth_token: UserAuthToken = None):
        self.account = account
        self.cookie = cookie
        self.auth_token = auth_token

    def get_token(self) -> str:
        if self.auth_token and self.auth_token.auth_token:
            return self.auth_token.auth_token
        return None

    def __repr__(self):
        return f"Auth(account={self.account}, cookie={self.cookie}, auth_token={self.auth_token})"


def save_tv_auth_data(auth: "Auth", path: str) -> bool:
    """Auth 데이터를 JSON 파일로 저장한다."""
    data = {}

    if auth.account:
        data["username"] = auth.account.uid
        data["password"] = auth.account.pw

    if auth.cookie:
        data["sessionid"] = auth.cookie.sessionid
        data["sessionid_sign"] = auth.cookie.sessionid_sign
        data["sessionid_exp"] = auth.cookie.expires_at.isoformat() if auth.cookie.expires_at else None

    if auth.auth_token:
        data["auth_token"] = auth.auth_token.auth_token
        data["auth_token_exp"] = auth.auth_token.expires_at.isoformat() if auth.auth_token.expires_at else None

    try:
        with open(path, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        logger.info(f"auth 데이터 저장 완료: {path}")
        return True
    except Exception as e:
        logger.error(f"auth 데이터 저장 실패: {e}")
        return False


def load_tv_auth_data(path: str) -> "Auth":
    """JSON 파일에서 Auth 데이터를 읽어 Auth 객체를 반환한다."""
    try:
        with open(path, "r") as f:
            data = json.load(f)
    except FileNotFoundError:
        logger.error(f"auth 데이터 파일 없음: {path}")
        return None
    except Exception as e:
        logger.error(f"auth 데이터 파일 읽기 실패: {e}")
        return None

    account = None
    username = data.get("username")
    password = data.get("password")
    if username and password:
        account = UserAccount(uid=username, pw=password)

    cookie = None
    sessionid = data.get("sessionid")
    sessionid_sign = data.get("sessionid_sign")
    if sessionid and sessionid_sign:
        expires_at = None
        sessionid_exp = data.get("sessionid_exp")
        if sessionid_exp:
            try:
                expires_at = datetime.fromisoformat(sessionid_exp)
            except (ValueError, TypeError):
                logger.warning(f"sessionid_exp 파싱 실패: {sessionid_exp}")
        cookie = UserCookie(sessionid=sessionid, sessionid_sign=sessionid_sign, expires_at=expires_at)

    auth_token = None
    token_str = data.get("auth_token")
    if token_str:
        expires_at = None
        auth_token_exp = data.get("auth_token_exp")
        if auth_token_exp:
            try:
                expires_at = datetime.fromisoformat(auth_token_exp)
            except (ValueError, TypeError):
                logger.warning(f"auth_token_exp 파싱 실패: {auth_token_exp}")
        auth_token = UserAuthToken(auth_token=token_str, expires_at=expires_at)

    logger.info(f"auth 데이터 로드 완료: {path}")
    return Auth(account=account, cookie=cookie, auth_token=auth_token)


def tradingview_login(account: UserAccount) -> tuple:
    """ID/PW로 TradingView에 로그인하여 (Auth, None) 또는 (None, error_msg)를 반환한다.

    - Set-Cookie에서 sessionid, sessionid_sign 추출
    - 응답 body JSON에서 auth_token 추출
    - RateLimitError는 raise (captcha, rate_limit, too_many_requests)
    """
    # multipart/form-data로 전송 (브라우저와 동일한 방식)
    # requests에서 files= 를 사용하면 자동으로 multipart/form-data 설정
    files = {
        "username": (None, account.uid),
        "password": (None, account.pw),
        "remember": (None, "true"),
    }

    try:
        resp = requests.post(
            SIGNIN_URL,
            files=files,
            headers=SIGNIN_HEADERS,
            timeout=10,
        )
    except Exception as e:
        logger.error(f"로그인 요청 실패: {e}")
        return None, f"login request failed: {e}"

    if resp.status_code != 200:
        logger.error(f"로그인 실패: HTTP {resp.status_code}")
        if resp.status_code == 429:
            raise RateLimitError("login rate limit: HTTP 429")
        return None, f"login failed: HTTP {resp.status_code}"

    content_type = resp.headers.get("Content-Type", "")
    if "application/json" not in content_type:
        logger.error(
            f"로그인 응답이 JSON이 아님 (Content-Type: {content_type}). "
            f"captcha 또는 HTML 응답 가능성. 앞부분: {resp.text[:300]}"
        )
        return None, f"login response is not JSON (Content-Type: {content_type}), possible captcha page"

    try:
        body = resp.json()
    except Exception as e:
        logger.error(f"응답 JSON 파싱 실패: {e}")
        return None, f"login response JSON parse failed: {e}"

    if "error" in body:
        error_type = body.get("error", "")
        error_code = body.get("code", "")
        rate_limit_codes = ("rate_limit", "captcha_required", "recaptcha_required", "too_many_requests")
        if error_type in rate_limit_codes or error_code in rate_limit_codes:
            raise RateLimitError(f"login blocked: {error_type} (code: {error_code})")
        logger.error(f"로그인 에러: {error_type} (code: {error_code})")
        return None, f"login error: {error_type} (code: {error_code})"

    # auth_token 추출
    try:
        token_str = body["user"]["auth_token"]
    except KeyError:
        logger.error(f"응답에 auth_token이 없음: {json.dumps(body)[:200]}")
        return None, "login response missing auth_token"

    # 쿠키 추출
    sessionid = resp.cookies.get("sessionid") or ""
    sessionid_sign = resp.cookies.get("sessionid_sign") or ""

    cookie = None
    if sessionid and sessionid_sign:
        cookie = UserCookie(
            sessionid=sessionid,
            sessionid_sign=sessionid_sign,
            expires_at=datetime.now() + timedelta(days=91),
        )
    else:
        logger.warning("응답에 sessionid 쿠키가 없음")

    auth = Auth(
        account=account,
        cookie=cookie,
        auth_token=UserAuthToken(
            auth_token=token_str,
        ),
    )

    logger.info(f"로그인 성공: {account.uid}")
    return auth, None


def refresh_auth_token(auth: Auth) -> str:
    """sessionid 쿠키로 /quote_token/ 에서 새 auth_token을 발급받는다.

    성공 시 auth.auth_token을 갱신하고 토큰 문자열을 반환한다.
    실패 시 None을 반환한다.
    """
    if not auth.cookie or not auth.cookie.sessionid:
        logger.error("sessionid가 없어 토큰 refresh 불가")
        return None

    cookies = {
        "sessionid": auth.cookie.sessionid,
        "sessionid_sign": auth.cookie.sessionid_sign,
    }

    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": SIGNIN_HEADERS["User-Agent"],
        "Origin": SIGNIN_HEADERS["Origin"],
        "Referer": SIGNIN_HEADERS["Referer"],
    }

    try:
        resp = requests.post(
            QUOTE_TOKEN_URL,
            headers=headers,
            cookies=cookies,
            data="",
            timeout=10,
        )
    except Exception as e:
        logger.error(f"quote_token 요청 실패: {e}")
        return None

    if resp.status_code != 200:
        logger.error(f"quote_token 실패: HTTP {resp.status_code}")
        if resp.status_code in (401, 403):
            logger.warning("sessionid가 서버에서 무효화됨")
            auth.cookie = None
        elif resp.status_code == 429:
            raise RateLimitError("refresh rate limit: HTTP 429")
        return None

    # Set-Cookie 체크 - sessionid가 갱신되었으면 쿠키 업데이트
    new_sessionid = resp.cookies.get("sessionid")
    new_sessionid_sign = resp.cookies.get("sessionid_sign")
    if new_sessionid and new_sessionid != auth.cookie.sessionid:
        logger.info(f"sessionid 갱신됨: {auth.cookie.sessionid[:8]}... -> {new_sessionid[:8]}...")
        auth.cookie.sessionid = new_sessionid
        auth.cookie.expires_at = datetime.now() + timedelta(days=91)
    if new_sessionid_sign and new_sessionid_sign != auth.cookie.sessionid_sign:
        logger.info("sessionid_sign 갱신됨")
        auth.cookie.sessionid_sign = new_sessionid_sign

    content_type = resp.headers.get("Content-Type", "")
    if "application/json" not in content_type and "text/plain" not in content_type:
        logger.error(
            f"quote_token 응답이 JSON이 아님 (Content-Type: {content_type}). "
            f"앞부분: {resp.text[:200]}"
        )
        return None

    try:
        token_str = resp.json()
        if isinstance(token_str, str) and token_str:
            auth.auth_token = UserAuthToken(auth_token=token_str)
            logger.info("auth_token refresh 성공")
            return token_str
        logger.error(f"quote_token 응답이 비정상: {token_str}")
        return None
    except Exception as e:
        logger.error(f"quote_token 응답 파싱 실패: {e}. 앞부분: {resp.text[:200]}")
        return None
