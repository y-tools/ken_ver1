# Kenのデンモク Ver.2 — 共有データ・ログイン

このブランチは2026-11-11時点のmain（TK限定98曲）を基準に、添付設計資料と旧PR #1の共有システムを移植した**未本番・要ステージング検証**の変更です。mainは変更していません。

## 機能
- Supabase Authによるメール・パスワードログイン、登録、確認メール、パスワード再設定
- listener/admin/ownerの3段階。新規登録はlistenerで固定し、管理者はowner招待後のメール確認で昇格
- RLSと認証済みロールチェックを含むサーバー側のRPC、操作ログ
- 共通保存：配信ON AIR、リクエスト、歌唱待機順・歌唱中/完了、歌える曲・練習中、配信履歴・レポート、管理メモ、DAM/JOYSOUND照合
- Realtimeはsync_versionの変更通知で更新し、サーバーから権限別の最新状態を取得。復帰時はポーリングで補完
- 既存のTK限定98曲カタログ、曲名とアーティスト名の2入力AND検索、VPS楽曲DB編集は独立したまま維持
- 旧ブラウザのリクエスト・歌唱履歴・歌える曲・管理メモ・カラオケ確認記録は移行せず、Ver.2で認証と共有スナップショット取得に成功した後、Ken専用の旧保存キーのみ削除（ほかのサイト・Supabaseセッションは削除しない）

## 本番との差分
- mainはTK限定98曲とVPS管理API、配信管理はローカル保存。本ブランチは配信管理をSupabaseへ切り替える試作です。
- GitHub Pages配信先はmainのみ。開発ブランチのファイルを置いただけでは本番に反映されません。
- 現状のSupabase URL・公開キーは空欄で、未設定時はフェイルクローズします。
- Ver.2改修仕様書の**Stripe決済・有料プラン・請求・契約制限は2026-11-11の指示で要件から除外**。複数ブランチ管理は別フェーズの未実装項目。自動曲収集は2026-11-09の停止方針を維持して復活させません。

## 公開準備（未実施）
1. 既存の同名テーブルと衝突しないSupabaseプロジェクトを用意し、スキーマをレビューしてください。
2. Supabase AuthでEmailのConfirm emailを有効化。Site URLを https://y-tools.github.io/ken_ver1/ にし、以下をRedirect URLに登録：
   - https://y-tools.github.io/ken_ver1/auth-callback.html
   - https://y-tools.github.io/ken_ver1/reset-password.html
3. supabase/migrations/202611070001_auth.sql → 002_live_data.sql → 003_actions.sql → 004_karaoke.sql の順でSQLを適用。
4. 初代ownerはメール確認済みの自分のアカウントを作成し、SQL Editorからprofiles.roleをownerに変更。公開ブラウザに昇格APIを作らない。
5. Supabase CLIでinvite-adminのEdge Functionをデプロイ。Service Role Keyはサーバー上の秘密情報だけに保存し、GitHubやブラウザには掲載しない。
6. config.jsのsupabaseUrlとsupabasePublishableKeyに**公開可能な**Project URLとpublishable/anon keyのみ設定。VPS検索のapiBaseUrlは従来通り。
7. 検証用環境で試験してからmainへ統合。稼働中の旧デンモクは先に切り替えない。

## 本番前の必須確認
- 登録→メール確認→ログイン→ログアウト→パスワード再設定
- listenerが管理者RPC・role変更を直接実行できないこと
- ownerが招待し、招待先のメール確認と期限内ログインでadminに昇格できること
- PCとスマホでON AIR→リクエスト→待機→歌唱開始→完了→終了が一致
- 複数管理者の同時編集、二重クリック、競合・切断・復旧時の画面動作
- 管理メモや未分類の他人のリクエストがlistenerへ返らないこと
- RLS、Realtime Publication、SQL関数の所有者、CORS、メール設定
- リスナー50人＋管理者3〜5人の実負荷試験

## 制約・移行注意
- 現在はSupabase URL・公開キーを設定していないため、共有データは動作しません。未設定時はローカル仮運用に戻らず画面を停止する設計。
- **旧ブラウザの保存記録は移行しません。** Ver.2は新しい共通DBの空の状態から開始します。旧端末データのバックアップ・移行・突合機能は不要です。
- **旧ブラウザデータの削除タイミング**：実認証＋共有スナップショットの成功後に限り、当該端末のKen専用localStorage 2キーを削除します。本番の旧ブラウザ版とVPSの楽曲DBは変更しません。
- **SQL実行・実認証・実Realtime・実メール送信・負荷試験は未実施**。コードの追加だけでは本番稼働を保証できません。
- 新規招待は実装しましたが、既存登録ユーザーへの管理者招待は追加設計が必要です。
- VPS側の楽曲DB編集認証は従来通り別管理。Supabaseのadmin権限はVPSの編集権限ではありません。
- 旧localStorage向けtests/smoke.mjsは新構成ではそのまま使用できません。失敗時閉鎖を確認するtests/shared-guard.mjsを追加しました。

## ロールバック
このブランチはmainに未統合です。本番公開前なら破棄可能です。本番切替前には新規共有DBのバックアップと切戻し手順を用意してください。旧ブラウザ記録の復元は要件外です。
