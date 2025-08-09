import os
import asyncio
import logging
import time
import base64
import discord
from discord.ext import tasks
import aiohttp
from dotenv import load_dotenv
from typing import List, Dict, Optional, Any
from Crypto.Hash import CMAC
from Crypto.Cipher import AES

# --- 初期設定 ---
# .envファイルから環境変数を読み込む
load_dotenv()

# ログ設定
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- 環境変数から設定を読み込み ---
# .strip() を追加して、キーの前後の不要な空白や改行を自動的に削除する
raw_key = os.getenv("SESAME_API_KEY", "")
# 見えない特殊文字などを強制的に除去するために、一度ASCIIにエンコード・デコードする
SESAME_API_KEY = raw_key.encode('ascii', 'ignore').decode('ascii').strip()
DEVICE_IDS_STR = os.getenv("SESAME_DEVICE_IDS", "").strip()
DEVICE_NAMES_STR = os.getenv("SESAME_DEVICE_NAMES", "").strip()
SESAME_SECRETS_STR = os.getenv("SESAME_SECRETS", "").strip()
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "").strip()
DISCORD_CHANNEL_ID_STR = os.getenv("DISCORD_CHANNEL_ID")
CHECK_INTERVAL_SECONDS_STR = os.getenv("CHECK_INTERVAL_SECONDS", "60")

# --- 設定値の検証と変換 (強化) ---
def validate_config():
    """起動時に環境変数が正しく設定されているかチェックする関数"""
    logging.info("環境変数の設定をチェックします...")
    errors = []
    
    if not SESAME_API_KEY or SESAME_API_KEY == "YOUR_SESAME_API_KEY":
        errors.append("SESAME_API_KEY が設定されていません。.env ファイルを確認してください。")
    
    if not DEVICE_IDS_STR or "YOUR_SESAME_DEVICE_UUID" in DEVICE_IDS_STR:
        errors.append("SESAME_DEVICE_IDS が設定されていません。.env ファイルを確認してください。")

    if not SESAME_SECRETS_STR:
        errors.append("SESAME_SECRETS が設定されていません。.env ファイルに各デバイスのシークレットキーを設定してください。")
        
    if not DISCORD_BOT_TOKEN or DISCORD_BOT_TOKEN == "YOUR_DISCORD_BOT_TOKEN":
        errors.append("DISCORD_BOT_TOKEN が設定されていません。.env ファイルを確認してください。")
        
    if not DISCORD_CHANNEL_ID_STR or DISCORD_CHANNEL_ID_STR == "YOUR_DISCORD_CHANNEL_ID":
        errors.append("DISCORD_CHANNEL_ID が設定されていません。.env ファイルを確認してください。")

    if errors:
        for error in errors:
            logging.error(error)
        logging.error("設定が不完全なため、ボットを起動できません。プログラムを終了します。")
        exit(1)
    
    try:
        global DISCORD_CHANNEL_ID, CHECK_INTERVAL_SECONDS, SESAME_DEVICE_IDS, DEVICE_CONFIGS
        DISCORD_CHANNEL_ID = int(DISCORD_CHANNEL_ID_STR)
        CHECK_INTERVAL_SECONDS = int(CHECK_INTERVAL_SECONDS_STR)
        SESAME_DEVICE_IDS = [uuid.strip() for uuid in DEVICE_IDS_STR.split(',')]
        SESAME_SECRETS = [secret.strip() for secret in SESAME_SECRETS_STR.split(',')]
        
        if len(SESAME_DEVICE_IDS) != len(SESAME_SECRETS):
            logging.error("SESAME_DEVICE_IDS と SESAME_SECRETS の数が一致しません。カンマ区切りの数を確認してください。")
            exit(1)

        SESAME_DEVICE_NAMES = [name.strip() for name in DEVICE_NAMES_STR.split(',')] if DEVICE_NAMES_STR else []

        DEVICE_CONFIGS = {}
        for i, uuid in enumerate(SESAME_DEVICE_IDS):
            DEVICE_CONFIGS[uuid] = {
                "name": SESAME_DEVICE_NAMES[i] if i < len(SESAME_DEVICE_NAMES) and SESAME_DEVICE_NAMES[i] else uuid,
                "secret": SESAME_SECRETS[i]
            }

        logging.info("環境変数のチェックが完了しました。設定は正常です。")

    except (ValueError, TypeError) as e:
        logging.error(f"環境変数の値の形式に誤りがあります: {e}")
        logging.error("DISCORD_CHANNEL_ID と CHECK_INTERVAL_SECONDS は数値である必要があります。")
        exit(1)

# 起動時に設定を検証
validate_config()


# --- Sesame API 関連 ---
SESAME_API_BASE_URL = "https://app.candyhouse.co/api/sesame2" # ステータス取得用

async def get_sesame_status(session: aiohttp.ClientSession, device_id: str) -> Optional[Dict[str, Any]]:
    """指定されたSesameデバイスの状態を取得します。"""
    url = f"{SESAME_API_BASE_URL}/{device_id}"
    try:
        # デバッグ: 実際にリクエストが送信される直前のURLとヘッダーを確認
        logging.info(f"Requesting status for {device_id} with headers: {session.headers}")
        async with session.get(url) as response:
            if response.status == 200:
                return await response.json()
            else:
                # 起動時のチェックで弾かれるはずだが、念のためログは残す
                logging.error(f"Sesame APIエラー (ステータス取得): {response.status} - {await response.text()}")
                return None
    except aiohttp.ClientError as e:
        logging.error(f"Sesame APIへの接続に失敗しました (ステータス取得): {e}")
        return None

def generate_sesame_sign(secret_hex: str) -> str:
    """Sesameコマンド用のAES-CMAC署名を生成します。"""
    key = bytes.fromhex(secret_hex)
    # 1. UNIXタイムスタンプ（秒）を取得
    ts = int(time.time())
    # 2. 4バイトのリトルエンディアンに変換
    # 3. 上位1バイトを削除して3バイトにする
    message = ts.to_bytes(4, 'little')[1:4]

    # AES-CMACを計算
    c = CMAC.new(key, ciphermod=AES)
    c.update(message)
    return c.hexdigest()

async def lock_sesame(session: aiohttp.ClientSession, device_id: str, secret_hex: str) -> bool:
    """指定されたSesameデバイスに施錠コマンドを送信します。"""
    # コマンド送信用のURLは末尾に /cmd が付く
    url = f"{SESAME_API_BASE_URL}/{device_id}/cmd"
    
    sign = generate_sesame_sign(secret_hex)
    history_tag = base64.b64encode("DiscordBot".encode()).decode()
    payload = {"cmd": 82, "history": history_tag, "sign": sign}
    
    try:
        logging.info(f"デバイス {device_id} に施錠コマンドを送信します。Payload: {{cmd: 82, history: '{history_tag}', sign: '{sign[:10]}...'}}")
        async with session.post(url, json=payload) as response:
            if response.status == 200:
                logging.info(f"デバイス {device_id} への施錠コマンド送信に成功しました。")
                return True
            else:
                logging.error(f"Sesame APIエラー (施錠): {response.status} - {await response.text()}")
                return False
    except aiohttp.ClientError as e:
        logging.error(f"Sesame APIへの接続に失敗しました (施錠): {e}")
        return False

# --- Discord UIコンポーネント ---
class UnlockNotificationView(discord.ui.View):
    """解錠通知に表示するボタンを持つViewクラス。"""
    def __init__(self):
        # timeoutをNoneにするとボタンが永続化するが、今回は24時間で無効化する
        super().__init__(timeout=86400) 
        self.add_item(discord.ui.Button(
            label="すべて施錠",
            style=discord.ButtonStyle.danger,
            custom_id="lock_all"
        ))

# --- Discord ボット本体 ---
class SesameBot(discord.Client):
    def __init__(self, *, intents: discord.Intents):
        super().__init__(intents=intents)
        self.http_session: Optional[aiohttp.ClientSession] = None
        # 最後に通知したメッセージを管理するための辞書
        self.last_notification_message_id: Optional[int] = None

    async def setup_hook(self) -> None:
        """ボットの初期化処理 (on_readyの前に呼ばれる)"""
        # セッション作成時に共通のヘッダーを設定する
        # これにより、各API呼び出しでヘッダーを都度設定する必要がなくなる
        headers = {"x-api-key": SESAME_API_KEY}
        # デバッグ用に、実際に設定されるヘッダーをログに出力
        logging.info(f"aiohttpセッションに設定するヘッダー: {headers}")
        self.http_session = aiohttp.ClientSession(headers=headers)
        self.check_sesame_status.start()

    async def on_ready(self):
        """ボットが起動したときに呼ばれるイベント"""
        logging.info(f'ボットが正常に起動しました: {self.user} (ID: {self.user.id})')
        channel = self.get_channel(DISCORD_CHANNEL_ID)
        if not channel:
            logging.error(f"指定されたチャンネル (ID: {DISCORD_CHANNEL_ID}) が見つかりません。")
        elif not isinstance(channel, discord.TextChannel):
             logging.error(f"指定されたIDはテキストチャンネルのものではありません。")

    async def on_interaction(self, interaction: discord.Interaction):
        """ボタンが押されたときなどに呼ばれるイベント"""
        if interaction.type != discord.InteractionType.component or interaction.data.get("custom_id") != "lock_all":
            return

        # ボタンを押したユーザーに即時応答し、処理中であることを示す
        await interaction.response.defer(ephemeral=True, thinking=True)

        # ボタンが押された時点で、再度解錠中のデバイスを確認する
        logging.info("「すべて施錠」ボタンが押されました。解錠中のデバイスを再チェックします。")
        status_tasks = [get_sesame_status(self.http_session, dev_id) for dev_id in SESAME_DEVICE_IDS]
        results = await asyncio.gather(*status_tasks)

        unlocked_devices_to_lock = []
        for i, status in enumerate(results):
            if status and status.get("CHSesame2Status") == "unlocked":
                device_id = SESAME_DEVICE_IDS[i]
                device_config = DEVICE_CONFIGS.get(device_id)
                if device_config:
                    unlocked_devices_to_lock.append({
                        "id": device_id,
                        "name": device_config.get("name", device_id),
                        "secret": device_config.get("secret")
                    })

        if not unlocked_devices_to_lock:
            await interaction.followup.send("✅ すべてのデバイスは既に施錠されていました。", ephemeral=True)
        else:
            # 解錠中のデバイスをすべて施錠する
            lock_tasks = [
                lock_sesame(self.http_session, device["id"], device["secret"])
                for device in unlocked_devices_to_lock
            ]
            lock_results = await asyncio.gather(*lock_tasks)

            success_devices = []
            failed_devices = []
            for i, success in enumerate(lock_results):
                device_name = unlocked_devices_to_lock[i]['name']
                if success:
                    success_devices.append(device_name)
                else:
                    failed_devices.append(device_name)

            # 応答メッセージの作成
            response_message = ""
            if success_devices:
                response_message += f"✅ **{', '.join(success_devices)}** を施錠しました。\n"
                logging.info(f"{interaction.user} が {', '.join(success_devices)} を施錠しました。")
            if failed_devices:
                response_message += f"❌ **{', '.join(failed_devices)}** の施錠に失敗しました。\n"
            await interaction.followup.send(response_message.strip(), ephemeral=True)

        # 元のメッセージのボタンを無効化する
        try:
            disabled_view = discord.ui.View(timeout=None)
            disabled_view.add_item(discord.ui.Button(label="すべて施錠", style=discord.ButtonStyle.danger, custom_id="lock_all", disabled=True))
            await interaction.message.edit(view=disabled_view)
        except discord.errors.NotFound:
            logging.warning("編集しようとした元のメッセージが見つかりませんでした。")
        except discord.errors.Forbidden:
            logging.error("メッセージを編集する権限がありません。")

    @tasks.loop(seconds=CHECK_INTERVAL_SECONDS)
    async def check_sesame_status(self):
        """定期的にSesameの状態をチェックするタスク"""
        unlocked_devices = []
        
        # 非同期に全デバイスの状態を取得
        tasks_to_run = [get_sesame_status(self.http_session, dev_id) for dev_id in SESAME_DEVICE_IDS]
        results = await asyncio.gather(*tasks_to_run)

        for i, status in enumerate(results):
            # 旧APIのレスポンス形式に合わせてキーを 'CHSesame2Status' に変更
            # レスポンスにdevice_idが含まれないため、リクエストに使ったIDを紐付ける
            if status and status.get("CHSesame2Status") == "unlocked":
                device_id = SESAME_DEVICE_IDS[i]
                unlocked_devices.append({
                    "id": device_id,
                    "name": DEVICE_CONFIGS.get(device_id, {}).get("name", device_id)
                })
        
        target_channel = self.get_channel(DISCORD_CHANNEL_ID)
        if not target_channel:
            logging.warning(f"通知先のチャンネル(ID: {DISCORD_CHANNEL_ID})が見つからないため、処理をスキップします。")
            return

        # 最後に送信した通知メッセージがまだ存在するか確認
        if self.last_notification_message_id:
            try:
                await target_channel.fetch_message(self.last_notification_message_id)
                # メッセージが存在する場合、新たな通知は送らない
                logging.info("前回の解錠通知がまだ残っているため、新しい通知は送信しません。")
                return
            except discord.errors.NotFound:
                # メッセージが存在しない（削除されたか、ボタンが押されて処理された）場合
                self.last_notification_message_id = None
        
        if unlocked_devices:
            logging.info(f"解錠されているデバイスを検出: {[d['name'] for d in unlocked_devices]}")
            
            embed = discord.Embed(
                title="🔓 解錠されているスマートロックがあります",
                description="下のボタンを押して、遠隔で施錠できます。",
                color=discord.Color.red()
            )
            for device in unlocked_devices:
                embed.add_field(name="デバイス名", value=f"**{device['name']}**", inline=False)
            
            view = UnlockNotificationView()
            try:
                message = await target_channel.send(embed=embed, view=view)
                # 新しく送信したメッセージのIDを保存
                self.last_notification_message_id = message.id
            except discord.errors.Forbidden:
                logging.error(f"チャンネル(ID: {DISCORD_CHANNEL_ID})へのメッセージ送信権限がありません。")

    @check_sesame_status.before_loop
    async def before_check_sesame_status(self):
        """タスクが開始される前に、ボットが準備完了するまで待つ"""
        await self.wait_until_ready()

    async def close(self):
        """ボットが終了するときに呼ばれる"""
        if self.http_session:
            await self.http_session.close()
        await super().close()

def main():
    # ボットが必要とするIntentsを設定
    intents = discord.Intents.default()
    intents.message_content = False # メッセージ内容の読み取りは不要

    # ボットをインスタンス化して実行
    client = SesameBot(intents=intents)
    
    try:
        client.run(DISCORD_BOT_TOKEN)
    except discord.errors.LoginFailure:
        logging.error("Discordボットのトークンが無効です。")
    except Exception as e:
        logging.error(f"ボットの実行中に予期せぬエラーが発生しました: {e}")

if __name__ == "__main__":
    main()
