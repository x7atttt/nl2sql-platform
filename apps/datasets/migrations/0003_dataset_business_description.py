# Generated for business_description field injection into NL2SQL prompt

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('datasets', '0002_datasetshare'),
    ]

    operations = [
        migrations.AddField(
            model_name='dataset',
            name='business_description',
            field=models.TextField(
                blank=True,
                default='',
                help_text='数据集业务背景/数据字典，注入 NL2SQL prompt 帮助理解字段语义',
                verbose_name='业务说明',
            ),
        ),
    ]
