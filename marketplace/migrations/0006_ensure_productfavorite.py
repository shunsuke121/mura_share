from django.db import migrations, models
import django.db.models.deletion
from django.conf import settings

def ensure_table(apps, schema_editor):
    conn = schema_editor.connection
    existing = set(conn.introspection.table_names())
    if 'marketplace_productfavorite' in existing:
        return
    # 直接CREATEする
    schema_editor.execute("""
        CREATE TABLE marketplace_productfavorite (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at DATETIME NOT NULL,
            user_id INTEGER NOT NULL REFERENCES auth_user(id) DEFERRABLE INITIALLY DEFERRED,
            product_id INTEGER NOT NULL REFERENCES marketplace_product(id) DEFERRABLE INITIALLY DEFERRED
        );
    """)
    schema_editor.execute(
        "CREATE UNIQUE INDEX uq_marketplace_productfavorite_user_product "
        "ON marketplace_productfavorite(user_id, product_id);"
    )

class Migration(migrations.Migration):

    dependencies = [
        ('marketplace', '0005_productfavorite_alter_purchase_options_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RunPython(ensure_table, migrations.RunPython.noop),
    ]
