import pytest
import logging
from unittest.mock import patch

# --- テスト対象の関数を main.py からインポート ---
# import時にトップレベルのコードが実行されないように修正済み
from main import generate_sesame_sign, validate_config

# --- generate_sesame_sign 関数のテスト ---
def test_generate_sesame_sign(mocker):
    """
    generate_sesame_signが固定のタイムスタンプに対して期待される署名を生成することをテストする。
    """
    # time.time() の戻り値を固定する
    fixed_timestamp = 1678886400  # 2023-03-15 12:00:00 UTC
    # main モジュール内で参照される time.time をパッチする
    mocker.patch('main.time.time', return_value=fixed_timestamp)

    # テスト用のシークレットキー
    secret_hex = "0102030405060708090a0b0c0d0e0f10"

    # 期待される署名 (テスト環境で固定のタイムスタンプから生成した値)
    # この値は、関数が意図せず変更されていないことを保証するためのリグレッションテストに用いる
    expected_sign = "f6394a513b283154103f802f411f0e05"

    # 実際の関数を呼び出す
    actual_sign = generate_sesame_sign(secret_hex)

    # 結果を検証
    assert actual_sign == expected_sign


# --- validate_config 関数のテスト ---
@pytest.fixture
def base_config():
    """正常な設定値の辞書を返すフィクスチャ"""
    return {
        "SESAME_API_KEY": "test_api_key",
        "SESAME_DEVICE_IDS": "uuid1,uuid2",
        "SESAME_DEVICE_NAMES": "name1,name2",
        "SESAME_SECRETS": "secret1,secret2",
        "DISCORD_BOT_TOKEN": "test_bot_token",
        "DISCORD_CHANNEL_ID": "1234567890",
        "CHECK_INTERVAL_SECONDS": "60",
        "DISCORD_MENTION_ON_UPDATE": "mention_role",
    }

def patch_main_globals(mocker, config):
    """指定された辞書の値で main モジュールのグローバル変数をパッチするヘルパー関数"""
    mocker.patch('main.SESAME_API_KEY', config.get("SESAME_API_KEY", ""))
    mocker.patch('main.DEVICE_IDS_STR', config.get("SESAME_DEVICE_IDS", ""))
    mocker.patch('main.DEVICE_NAMES_STR', config.get("SESAME_DEVICE_NAMES", ""))
    mocker.patch('main.SESAME_SECRETS_STR', config.get("SESAME_SECRETS", ""))
    mocker.patch('main.DISCORD_BOT_TOKEN', config.get("DISCORD_BOT_TOKEN", ""))
    mocker.patch('main.DISCORD_CHANNEL_ID_STR', config.get("DISCORD_CHANNEL_ID", ""))
    mocker.patch('main.CHECK_INTERVAL_SECONDS_STR', config.get("CHECK_INTERVAL_SECONDS", "60"))
    mocker.patch('main.DISCORD_MENTION_ON_UPDATE', config.get("DISCORD_MENTION_ON_UPDATE", ""))

    # テスト中に exit() が呼ばれるのを防ぎ、代わりに例外を発生させる
    mocker.patch('builtins.exit', side_effect=SystemExit)
    # ログ出力をキャプチャできるようにモックする
    mocker.patch('logging.error')


def test_validate_config_success(mocker, base_config):
    """すべての設定が正常な場合に、エラーなく完了することをテストする。"""
    patch_main_globals(mocker, base_config)

    try:
        validate_config()
    except SystemExit:
        pytest.fail("正常な設定で SystemExit が呼ばれました。")

    logging.error.assert_not_called()


@pytest.mark.parametrize("missing_key, error_message_part", [
    ("SESAME_API_KEY", "SESAME_API_KEY が設定されていません"),
    ("SESAME_DEVICE_IDS", "SESAME_DEVICE_IDS が設定されていません"),
    ("SESAME_SECRETS", "SESAME_SECRETS が設定されていません"),
    ("DISCORD_BOT_TOKEN", "DISCORD_BOT_TOKEN が設定されていません"),
    ("DISCORD_CHANNEL_ID", "DISCORD_CHANNEL_ID が設定されていません"),
])
def test_validate_config_missing_vars(mocker, base_config, missing_key, error_message_part):
    """必須の環境変数が欠けている場合に、SystemExit が呼ばれ、適切なエラーメッセージが出力されることをテストする。"""
    base_config[missing_key] = ""
    patch_main_globals(mocker, base_config)

    with pytest.raises(SystemExit):
        validate_config()

    calls = logging.error.call_args_list
    assert any(error_message_part in str(call) for call in calls)


def test_validate_config_id_secret_mismatch(mocker, base_config):
    """デバイスIDとシークレットの数が不一致の場合にエラー終了することをテストする。"""
    base_config["SESAME_SECRETS"] = "secret1"  # IDは2つ、Secretは1つ
    patch_main_globals(mocker, base_config)

    with pytest.raises(SystemExit):
        validate_config()

    calls = logging.error.call_args_list
    assert any("数が一致しません" in str(call) for call in calls)


def test_validate_config_invalid_number_format(mocker, base_config):
    """数値であるべき設定が文字列の場合にエラー終了することをテストする。"""
    base_config["CHECK_INTERVAL_SECONDS"] = "not_a_number"
    patch_main_globals(mocker, base_config)

    with pytest.raises(SystemExit):
        validate_config()

    calls = logging.error.call_args_list
    assert any("値の形式に誤りがあります" in str(call) for call in calls)


# --- API連携部分のテスト ---
# aiohttp.ClientSession をモックするための準備
@pytest.fixture
def mock_aiohttp_session(mocker):
    """aiohttp.ClientSession のモックを返すフィクスチャ"""
    # ClientSession自体は同期オブジェクト
    mock_session = mocker.MagicMock()

    # get()やpost()メソッドが返すのは非同期コンテキストマネージャ
    # そのため、return_value に AsyncMock を設定する
    mock_session.get.return_value = mocker.AsyncMock()
    mock_session.post.return_value = mocker.AsyncMock()

    # close() は非同期メソッド
    mock_session.close = mocker.AsyncMock()

    return mock_session

@pytest.mark.asyncio
async def test_get_sesame_status_success(mocker, mock_aiohttp_session):
    """get_sesame_status が正常にステータスを取得できることをテストする。"""
    from main import get_sesame_status

    device_id = "test_uuid"
    expected_status = {"CHSesame2Status": "locked", "batteryPercentage": 88}

    # レスポンスのモックを作成
    mock_response = mocker.AsyncMock()
    mock_response.status = 200
    mock_response.json.return_value = expected_status

    # session.get().__aenter__() がレスポンスのモックを返すように設定
    mock_aiohttp_session.get.return_value.__aenter__.return_value = mock_response

    status = await get_sesame_status(mock_aiohttp_session, device_id)

    # アサーション
    mock_aiohttp_session.get.assert_called_once_with(f"https://app.candyhouse.co/api/sesame2/{device_id}")
    assert status == expected_status

@pytest.mark.asyncio
async def test_get_sesame_status_api_error(mocker, mock_aiohttp_session):
    """get_sesame_status がAPIエラー時に None を返すことをテストする。"""
    from main import get_sesame_status
    mocker.patch('logging.error')

    device_id = "test_uuid"

    mock_response = mocker.AsyncMock()
    mock_response.status = 500
    mock_response.text.return_value = "Internal Server Error"

    mock_aiohttp_session.get.return_value.__aenter__.return_value = mock_response

    status = await get_sesame_status(mock_aiohttp_session, device_id)

    assert status is None
    logging.error.assert_called_once()


@pytest.mark.asyncio
async def test_lock_sesame_success(mocker, mock_aiohttp_session):
    """lock_sesame が正常に施錠コマンドを送信できることをテストする。"""
    from main import lock_sesame, generate_sesame_sign

    device_id = "test_uuid"
    secret = "0102030405060708090a0b0c0d0e0f10"

    # generate_sesame_sign が固定値を返すようにモック
    mocker.patch('main.generate_sesame_sign', return_value="mock_sign")

    mock_response = mocker.AsyncMock()
    mock_response.status = 200
    mock_aiohttp_session.post.return_value.__aenter__.return_value = mock_response

    result = await lock_sesame(mock_aiohttp_session, device_id, secret)

    assert result is True
    mock_aiohttp_session.post.assert_called_once()
    # payload の中身も検証できるとより良いが、ここでは省略
    # call_args[1]['json'] で json payload を取得可能


@pytest.mark.asyncio
async def test_lock_sesame_api_error(mocker, mock_aiohttp_session):
    """lock_sesame がAPIエラー時に False を返すことをテストする。"""
    from main import lock_sesame
    mocker.patch('logging.error')

    device_id = "test_uuid"
    secret = "0102030405060708090a0b0c0d0e0f10"

    mock_response = mocker.AsyncMock()
    mock_response.status = 401
    mock_response.text.return_value = "Unauthorized"
    mock_aiohttp_session.post.return_value.__aenter__.return_value = mock_response

    result = await lock_sesame(mock_aiohttp_session, device_id, secret)

    assert result is False
    logging.error.assert_called_once()
