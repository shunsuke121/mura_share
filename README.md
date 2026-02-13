# プロジェクト名・概要

## MURAシェア

MURAシェアは、地域コミュニティ内でモノを「貸す・借りる・売る・買う」ための Web アプリです。  
画面（Django Templates）と API（Django REST Framework）を同時に提供します。

# デモ・スクリーンショット

- ローカルデモ URL: `http://127.0.0.1:8000/products/`
- API ドキュメント: `http://127.0.0.1:8000/api/docs/`
- OpenAPI スキーマ: `http://127.0.0.1:8000/api/schema/`
- スクリーンショット: 現在は未配置（必要なら `docs/screenshots/` などに追加）

# 機能・特徴

- 商品出品（画像、カテゴリ、在庫、レンタル/販売区分）
- レンタル申請フロー（申請、承認、発送、受取、返却、完了）
- 購入フロー（申請、承認、発送、受取、返品）
- 取引に紐づくチャット
- 通知機能
- お問い合わせフォーム（添付ファイル対応）
- 管理者向け配送管理画面

# インストール・セットアップ

1. 仮想環境を作成して有効化

```powershell
python -m venv .venv
.\.venv\Scripts\activate
```

2. 依存パッケージをインストール  
このリポジトリに `requirements.txt` はないため、以下を直接実行します。

```powershell
pip install "Django>=4.2,<6.0" djangorestframework djangorestframework-simplejwt drf-spectacular django-filter django-cors-headers drf-nested-routers pillow requests
```

3. マイグレーション実行

```powershell
python manage.py migrate
```

4. 管理ユーザー作成（任意）

```powershell
python manage.py createsuperuser
```

# 使用方法

1. 開発サーバーを起動

```powershell
python manage.py runserver
```

2. ブラウザで `http://127.0.0.1:8000/products/` を開く
3. 必要に応じて `/signup/` でユーザー登録、`/login/` でログイン
4. 商品登録、レンタル申請、購入申請、チャットを操作して動作確認
5. 管理者は `http://127.0.0.1:8000/admin/` と `http://127.0.0.1:8000/admin/shipping/` を利用

# API・設定

主要 API（抜粋）:

- `GET/POST /api/v1/products/`
- `GET/POST /api/v1/rentals/`
- `GET/POST /api/v1/purchases/`
- `GET/POST /api/v1/notifications/`
- `GET/POST /api/v1/rooms/`
- `GET/POST /api/v1/products/{product_id}/images/`
- `GET/POST /api/v1/rooms/{room_id}/messages/`

認証 API:

- `POST /api/v1/auth/register/`
- `POST /api/v1/auth/jwt/create/`
- `POST /api/v1/auth/jwt/refresh/`
- `GET /api/v1/auth/me/`

環境変数:

- `DJANGO_SECRET_KEY`（任意）
- PostgreSQL を使う場合は `mura_share/settings.py` の DB 設定を切り替えた上で以下を使用
- `POSTGRES_DB`
- `POSTGRES_USER`
- `POSTGRES_PASSWORD`
- `POSTGRES_HOST`
- `POSTGRES_PORT`

補足:

- `/api/schema/` はシリアライザ定義が不整合だとエラーになります。  
  エラー時は `marketplace/serializers.py` の `PurchaseSerializer` など、モデルと serializer のフィールド整合を確認してください。

# 貢献方法

1. ブランチを作成して変更
2. 変更内容を確認（最低限 `python manage.py check` と画面/API の簡易動作確認）
3. 変更理由が分かるコミットメッセージでコミット
4. Pull Request を作成


# ライセンス・作者情報

- ライセンス: 現在このリポジトリに `LICENSE` ファイルはありません（必要なら追加してください）
- 作者情報: プロジェクト管理者情報は未記載です
