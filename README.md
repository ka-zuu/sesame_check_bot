# Sesame-Discord監視ボット (Sesame Discord Monitor Bot)

CANDY HOUSE製のスマートロック「セサミ」の状態を監視し、解錠された場合にDiscordへ通知を送るためのボットです。

## 主な機能

- **定期的な状態監視**: 指定した間隔でセサミの状態を自動的にチェックします。
- **解錠通知**: セサミが「解錠」状態の場合に、指定したDiscordチャンネルへ通知を送信します。
- **遠隔施錠**: 通知メッセージに付属する「すべて施錠」ボタンを押すことで、解錠されているすべてのセサミを遠隔で施錠できます。
- **バッテリー残量表示**: 通知時に、デバイスのバッテリー残量も合わせて表示します。
- **複数デバイス対応**: 複数のセサミデバイスを同時に監視できます。

## 必要なもの

- Python 3.8 以上
- CANDY HOUSE APIキー
- Discordボットトークン

## セットアップ手順

### 1. リポジトリをクローン

```bash
git clone https://github.com/your-username/sesame-discord-bot.git
cd sesame-discord-bot
```

### 2. 依存関係のインストール

必要なライブラリをインストールします。

```bash
pip install -r requirements.txt
```

### 3. .env ファイルの設定

プロジェクトのルートディレクトリに `.env` という名前のファイルを作成し、以下の内容をコピーして、ご自身の環境に合わせて値を設定してください。

```dotenv
# --- Sesame API設定 ---
# CANDY HOUSEから発行されたAPIキー
SESAME_API_KEY="YOUR_SESAME_API_KEY"
# 監視したいセサミのUUID (カンマ区切りで複数指定可能)
SESAME_DEVICE_IDS="YOUR_SESAME_DEVICE_UUID_1,YOUR_SESAME_DEVICE_UUID_2"
# 各デバイスのシークレットキー (デバイスIDと同じ順番でカンマ区切りで指定)
SESAME_SECRETS="YOUR_SESAME_SECRET_1,YOUR_SESAME_SECRET_2"
# (任意) 各デバイスの表示名 (デバイスIDと同じ順番でカンマ区切りで指定)
SESAME_DEVICE_NAMES="玄関,勝手口"

# --- Discord Bot設定 ---
# Discord Developer Portalで取得したボットのトークン
DISCORD_BOT_TOKEN="YOUR_DISCORD_BOT_TOKEN"
# 通知を送信したいDiscordチャンネルのID
DISCORD_CHANNEL_ID="YOUR_DISCORD_CHANNEL_ID"

# --- 動作設定 ---
# (任意) セサミの状態をチェックする間隔 (秒単位、デフォルトは60秒)
CHECK_INTERVAL_SECONDS="60"
# (任意) 通知時にメンションしたいユーザーやロールのID
DISCORD_MENTION_ON_UPDATE=""
```

## 環境変数の説明

| 変数名 | 説明 | 取得方法 |
| --- | --- | --- |
| `SESAME_API_KEY` | CANDY HOUSEのAPIを利用するためのキーです。 | セサミアプリの「API設定」から発行できます。 |
| `SESAME_DEVICE_IDS` | 監視対象のセサミのUUIDです。 | セサミアプリでデバイスを選択し、「デバイスの設定」画面で確認できます。 |
| `SESAME_SECRETS` | コマンド送信（施錠など）に必要なシークレットキーです。 | セサミアプリでデバイスを選択し、「デバイスの設定」画面で確認できます。 |
| `SESAME_DEVICE_NAMES` | Discordの通知に表示されるデバイス名です。設定しない場合はUUIDが表示されます。 | 自由な名前を設定できます。 |
| `DISCORD_BOT_TOKEN` | ボットをDiscordに接続するためのトークンです。 | [Discord Developer Portal](https://discord.com/developers/applications)でアプリケーションを作成し、「Bot」タブから取得します。 |
| `DISCORD_CHANNEL_ID` | ボットが通知を送信するテキストチャンネルのIDです。 | Discordでチャンネルを右クリックし、「チャンネルIDをコピー」を選択します（開発者モードを有効にする必要があります）。 |
| `CHECK_INTERVAL_SECONDS` | デバイスの状態を確認する頻度（秒）です。デフォルトは`60`です。 | |
| `DISCORD_MENTION_ON_UPDATE` | 解錠通知の際にメンションしたいユーザーIDやロールIDです。 | ユーザーやロールを右クリックしてIDをコピーします。 |

## 実行方法

設定が完了したら、以下のコマンドでボットを起動します。

```bash
python main.py
```

ボットが正常に起動すると、コンソールにログが表示されます。

## 仕組み

1.  ボットは起動すると、`CHECK_INTERVAL_SECONDS`で設定された間隔で `check_sesame_status` タスクを実行します。
2.  このタスクは、`SESAME_DEVICE_IDS`で指定されたすべてのセサミデバイスの状態をCANDY HOUSE API経由で取得します。
3.  状態が「unlocked (解錠)」のデバイスが見つかった場合、ボットは`DISCORD_CHANNEL_ID`で指定されたチャンネルに通知を送信します。
4.  通知には「すべて施錠」ボタンが含まれており、ユーザーがこのボタンを押すと、`on_interaction` イベントがトリガーされます。
5.  `on_interaction` イベントは、解錠中のデバイスに施錠コマンドを送信し、結果をDiscordメッセージで報告します。