# Generated for 查询历史结果预览持久化

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('query', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='queryhistory',
            name='result_count',
            field=models.IntegerField(default=0, verbose_name='结果行数'),
        ),
        migrations.AddField(
            model_name='queryhistory',
            name='result_preview',
            field=models.JSONField(blank=True, null=True, verbose_name='结果预览(前20行)'),
        ),
        migrations.AddField(
            model_name='queryhistory',
            name='result_columns',
            field=models.JSONField(blank=True, null=True, verbose_name='结果列名'),
        ),
    ]
