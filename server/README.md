# Kenのデンモク — VPS検索DB（Phase 0）

GitHub Pagesの現行2,000,000件検索を維持し、専用PostgreSQLとHTTPS APIを段階導入する構成です。現時点で**VPSへは未インストール**。実機の空き容量・メモリ・CPU・稼働中のMinecraft等・既存Webサーバーを調べるまでデプロイしません。

## 主要ファイル
- server/sql/001_init.sql — 楽曲、アーティスト、録音バージョン、発売日証拠、出典、4種類の別名
- server/api/main.py — 読み取り専用API。曲名・アーティスト切替、2文字以上の前方一致検索、最大50件
- server/import_catalog.py — 既存200万件と日本語自動推定読みをファイル単位で分割取り込み
- server/requirements.txt — FastAPI、psycopg、uvicorn
- server/.env.example — VPS内部の環境変数ひな型（本物のパスワードをGitHubへ公開しない）
- server/systemd-example.service — ローカルポート8787のAPIサービス例
- server/nginx-example.conf — HTTPSとレート制限を掛けるリバースプロキシ例
- data/vps-search.js — GitHub Pagesからの任意接続。URL未設定や接続障害時は従来の静的検索を利用

## 表記の正確性
曲名・アーティスト各々に、ひらがな、カタカナ、ローマ字、英語名を別々に登録します。複数候補を許可し、**各表記ごと**に出典と、推定／出典確認済み／人による確認済み／確認済みからの派生、という検証状態を持ちます。

- 推定かなは検索補助には使えますが、正式読みに昇格させません
- ローマ字は確認済みかなからの派生を識別し、公式固有ローマ字表記があれば公式表記を優先します
- 英語欄は**正式な英語タイトル・公式英語アーティスト名だけ**。機械翻訳を正式英語名として登録しません
- 既存の自動生成日本語読み（約31.8万件）を取り込む場合は全件「推定」扱いです
- 発売日は不明／年のみ／年月／年月日を分けます。不明な日を1月1日で埋めません
- 同名同アーティストを暫定的に一つに集約しますが、同名異曲・再録音は後の出典照合で録音IDと別バージョンを区別する必要があります

## VPSで最初に確認する項目（停止しない読み取りのみ）
OS、メモリ・CPU負荷、ディスク・inode、既存のTCPポート、PostgreSQL有無、Nginx／Apache／Dockerの構成、既存サービスの自動起動、バックアップ先。例えば次のコマンドです。

    cat /etc/os-release
    free -h
    df -h
    df -i
    lsblk -f
    ss -lnt
    systemctl list-units --type=service --state=running
    ps -eo comm,rss --sort=-rss | head -n 20
    pg_isready || true

**既存VPSの容量が不明なうちは全200万件を投入しません。** メタデータ、インデックス、ステージング、バックアップには数GB以上必要になる可能性があります。

## 安全な導入手順
1. 実機調査とバックアップ確認。必要ならインデックス・本体データは別ディスクへ置きます。
2. PostgreSQL 16以降を既存サービスと競合しないようインストール。データベースの5432は外部公開せず、localhostのみに限定します。
3. DB所有者、読み取り専用の ken_search、取り込み専用の ken_import を別ロールにします。テーブルへのSELECTだけをAPIロールへ許可します。
4. 管理者として server/sql/001_init.sql を一度適用。これは楽曲専用の新テーブルを作るだけで、既存サービスを削除しません。
5. Pythonのvenvを作りserver/requirements.txtを導入。機密情報はVPS内の /etc/ken-song-api.env などへ保管し、権限600にします。
6. import_catalog.py はまず --dataset japanese --max-files 1 で試験投入。バッチで投入中のメモリ・容量・応答時間を観察し、段階を拡張します。
7. systemdの例を実環境に合わせてAPIを127.0.0.1:8787だけで起動します。
8. HTTPS API用の**専用サブドメイン**を用意し、既存Nginxを壊さずにレート制限付きで中継します。CORSは https://y-tools.github.io だけを許可します。
9. HTTPSの健全性と「/api/v1/search?q=xxx&mode=title」を確認してから、公開してよい**HTTPS API URLだけ**を GitHub Pagesの config.js に設定します。PostgreSQLの接続情報は絶対に公開しません。
10. 段階的に旧カタログ全体を移行し、出典付き発売日と確認済みの読みを増やしていきます。現行のリクエスト機能は引き続き別系統です。

## 構築後の4段階
1. Phase 1：既存200万件の正規化、重複・バージョンの整理
2. Phase 2：出典付きの発売日（日付精度を含む）の大量補完
3. Phase 3：日本楽曲を優先して不足曲と**正確な4種類の読み**を追加
4. Phase 4：定期差分収集・検証・承認による情報修正

MusicBrainzなどのCC0データを優先し、VocaDBなどCC BYは出典表示を継続。収録曲カタログは音源・歌詞・カラオケ収録状況を保証しません。歌配信利用許諾とも別です。


## 楽曲データベースのWeb編集画面（2026-11-06）

GitHub Pagesのデンモク管理画面（タイトル長押し→従来の簡易ログイン）に **「楽曲データベース編集」** リンクを追加しました。専用ページは `https://y-tools.github.io/ken_ver1/database-editor.html` です。

このページでは、VPS側の**別の管理者パスワード**でログインして、アーティスト検索→選択→楽曲一覧→曲名・リリース日・ひらがな／カタカナ／ローマ字／正式英語表記を編集できます。変更は履歴テーブル `ken_admin_audit` に保存し、他の編集との更新競合は409で拒否します。登録した読みは手動で確認したものとして扱います。公式根拠がある場合は出典URLを登録してください。

### 初回管理者パスワード

- 初期パスワードは約40文字のランダム文字列で、VPSのroot専用ファイル `/root/ken-song-editor-initial-password.txt` に保存済みです。**GitHubやブラウザコードには含めません**。
- VPSへSSH接続可能な所有者は、手元の端末で次を実行して初期パスワードを確認できます。

```sh
ssh ubuntu@153.127.64.17 "sudo cat /root/ken-song-editor-initial-password.txt"
```

- 初回ログイン後は、SSH上の対話入力で**自分だけの16文字以上のパスワードに変更**してください。

```sh
ssh -t ubuntu@153.127.64.17 "sudo /opt/ken-song-api/.venv/bin/python /opt/ken-song-api/server/reset-admin-password.py"
```

- パスワード変更時はサーバー側の認証セッションを全失効させ、初期パスワードのファイルを削除します。新パスワードは標準出力やGitHubに表示されません。
- 既存の `kny` はフロントエンドの管理画面表示切替のみで、**DB編集権限は与えません**。編集APIは別systemdサービス `ken-song-admin.service`（`127.0.0.1:8788`）と、既存Caddyホストの `/api/admin/*` で中継します。
- Argon2idハッシュによる認証、30分で切れるメモリ上のBearerセッション、5回／15分のログイン試行制限、GitHub PagesへのCORS限定、別権限のPostgreSQLユーザーを採用しています。
- データベースの削除や曲の一括削除は、この画面からはできません。正式な英語表記の自動翻訳も行いません。初期段階では既存レコードの安全な修正に限定しています。

## 重要な未完了項目
VPS実機容量検証、DBユーザー設定、HTTPS API公開、200万件の移行、公式読み・発売日の全面照合、定期収集は**まだ未実施**です。ファイルをGitHubへ置いただけで本番サービスが稼働したとは扱いません。

## アーティスト最終調査日（2026-11-09）

- `artists.last_researched_on DATE NULL` を追加。空欄は未確認で、アーティスト名・曲情報を通常編集しても自動更新しません。
- 管理者画面の「アーティスト基本情報」で最終調査日を独立して表示・保存できます。管理APIは `GET /api/admin/artists/{id}` と `POST /api/admin/artists/{id}/research`（本人確認済みBearerセッション、楽観ロック、履歴記録）です。
- 未来の日付は登録できず、意図的に空欄へ戻せます。履歴は `ken_admin_audit` に保管します。通常の公開検索APIに変更はありません。
- 実際に調査した TK from 凛として時雨（ID 643167）の最終調査日は **2026-11-08**。他のアーティストの既存レコードはNULLのままです。
- 初回は `server/sql/003_admin_editor.sql` の後に `server/sql/020_artist_last_researched_on.sql` を実行し、当該アーティストの記録は `server/sql/021_tk_research_date_20261108.sql` に記載。修正・適用前にバックアップと検証を行ってください。
