# Kenのデンモク Ver.2 — 本番移行手順と判定（2026-11-11）

状態: **未本番**。現在はGitHub Draft PR #15で実装・模擬テスト済みですが、実Supabaseプロジェクト接続、SQL実行、Edge Function配布、実認証テスト、本番切替は未実施。

## 事前条件
- 権限のあるSupabaseプロジェクトを接続し、可能なら専用ステージングと本番を分ける。
- 本番公開の`main`をバックアップして切戻し方法を決める。
- GitHub Pagesに記載してよいのはSupabase Project URLと**公開可能なPublishable/anon keyのみ**。Service role、DBパスワード、アクセストークンは決して公開リポジトリに置かない。
- 旧ブラウザ保存分の移行、決済・Stripe、旧200万曲自動登録は要件外。TK限定98曲、既存VPS楽曲DBを保全する。

## 1. ステージングでのDB準備
次の7件の`supabase/migrations/`のファイルを**番号順**に適用・検証する。
1. `202611070001_auth.sql` — profiles、listener/admin/owner、管理者招待
2. `202611070002_live_data.sql` — 配信・曲・チャット・リクエスト・履歴・共有更新番号
3. `202611070003_actions.sql` — 権限付き操作RPC・表示用スナップショット
4. `202611070004_karaoke.sql` — DAM/JOYSOUND確認
5. `202611110005_login_id.sql` — ログインID＋パスワード、重複防止・試行制限
6. `202611110006_online_presence.sql` — 認証済み接続更新、管理者一覧、RLS、Realtime
7. `202611110007_revoke_signup_trigger_execution.sql` — 登録トリガー関数の不要な公開RPC権限を撤回

既存テーブル、関数、Publication/RLSと衝突しないかデプロイ前にレビューする。Supabase CLIを使用する場合、公式ドキュメントに従って接続後に`supabase db push --remote`で適用する。権限ある環境への適用は慎重に行い、SQL実行ログを残す。

## 2. 認証と関数
- Email/Passwordとメール確認を有効化。メール送信/再設定をテストする。
- Site URL: `https://y-tools.github.io/ken_ver1/`
- Redirect URL: `/ken_ver1/auth-callback.html`と`/ken_ver1/reset-password.html`を許可。
- 初代ownerは本人がメール確認後、信頼できるSupabase管理者がSQL側で昇格。Webに公開昇格APIを作らない。
- `invite-admin`は認証済みownerのみ、`login-with-id`はJWTなしのログイン前操作だが関数内でパスワード照合とレート制限を必須とする。
- 上記2つのEdge Functionsを環境別にデプロイし、サービス用秘密鍵はSupabase側だけに保持する。

## 3. 共有状態の検証対象
| 情報 | 共有データ |
|---|---|
| 配信開始・終了、名前、配信レポート | `stream_status`, `stream_sessions`, `session_events` |
| リクエスト、待機順、歌唱・履歴 | `requests`, `queue`, `singing_history` |
| 歌える曲、練習中、曲メモ | `songs` |
| 管理者チャット・調査メモ | `admin_notes`（リスナーに非公開） |
| DAM/JOYSOUND確認 | `karaoke_records` |
| ユーザー・権限・ログインID | Supabase Auth, `profiles` |
| オンライン接続状況 | `online_sessions` |

配信管理状態は`sync_version`のRealtime通知および4秒の再取得で同期する。ログイン中一覧は`online_sessions`への更新通知と5秒ポーリングを併用する。Supabase PublicationとRLSの許可を実機で検証し、管理者以外にはプロフィール一覧・管理チャットを返さない。

## 4. 本番切替の合格条件
- [ ] ステージングSQL適用、RLS、ログインID/メールログイン、確認メール・再設定の実試験
- [ ] owner管理者招待、通常listener権限拒否、セッション無効化の実試験
- [ ] 管理者2名＋別PC/スマホのリスナーでON AIR/OFF AIR、チャット・待機・曲リストの更新確認
- [ ] 同じユーザーの複数タブは1人に集約、ログアウトと切断時の一覧変化を確認
- [ ] 50人リスナー＋管理者3〜5人の負荷・接続断/復旧・同時編集試験
- [x] 新規SupabaseにSQL7件・Functions2件を適用（実ユーザーと受入試験は別途）
- [ ] 本番SupabaseのAuthメール・リダイレクト・owner設定と実端末受入試験
- [ ] `config.js`に公開用URL/keyを設定済みのDraft PR #15を実認証テスト後にレビューしてmainへマージ
- [ ] GitHub Pagesの本番URLで確認、失敗時のrollbackに成功

**接続未設定のままPRをmainへマージすると、認証必須のVer.2が開けなくなります。本番テストが通るまでマージしない。**

## 5. 切戻し
GitHubのmainへ入れた切替変更をrevertしてPagesの前バージョンへ戻す。Supabase新規データは保持して調査し、VPSの既存楽曲DBには触れない。

参考（公式）:
- https://supabase.com/docs/guides/deployment/managing-environments
- https://supabase.com/docs/guides/realtime/subscribing-to-database-changes
- https://supabase.com/docs/guides/functions/deploy
