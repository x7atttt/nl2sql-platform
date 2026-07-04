from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('datasets', '0003_dataset_business_description'),
    ]

    operations = [
        migrations.AddField(
            model_name='dataset',
            name='suggested_questions',
            field=models.JSONField(
                blank=True,
                null=True,
                help_text='LLM 生成的 4 条推荐查询，供用户点击填入查询框',
                verbose_name='推荐查询',
            ),
        ),
    ]
