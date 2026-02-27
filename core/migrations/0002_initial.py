import django.db.models.deletion
import pgvector.django
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0001_enable_pgvector'),
    ]

    operations = [
        migrations.CreateModel(
            name='Company',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('handle', models.CharField(blank=True, max_length=512, null=True, unique=True)),
                ('name', models.CharField(max_length=255)),
                ('url', models.URLField(blank=True, null=True)),
                ('website', models.CharField(blank=True, help_text='Raw domain from CSV', max_length=255, null=True)),
                ('industry', models.CharField(blank=True, max_length=255, null=True)),
                ('size', models.CharField(blank=True, max_length=50, null=True)),
                ('type', models.CharField(blank=True, max_length=100, null=True)),
                ('founded', models.CharField(blank=True, max_length=10, null=True)),
                ('city', models.CharField(blank=True, max_length=255, null=True)),
                ('state', models.CharField(blank=True, max_length=255, null=True)),
                ('country_code', models.CharField(blank=True, max_length=10, null=True)),
                ('scrape_status', models.CharField(choices=[('pending', 'Pending'), ('in_progress', 'In Progress'), ('success', 'Success'), ('error', 'Error')], default='pending', max_length=15)),
                ('scrape_error_type', models.CharField(blank=True, max_length=50, null=True)),
                ('scrape_error_detail', models.TextField(blank=True, null=True)),
                ('scraped_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'indexes': [
                    models.Index(fields=['scrape_status'], name='core_compan_scrape__a1b2c3_idx'),
                    models.Index(fields=['industry'], name='core_compan_industr_d4e5f6_idx'),
                    models.Index(fields=['country_code'], name='core_compan_country_g7h8i9_idx'),
                ],
            },
        ),
        migrations.CreateModel(
            name='ScrapedData',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('text_content', models.TextField(help_text='Raw text content from the website')),
                ('cleaned_content', models.TextField(blank=True, help_text='Preprocessed logical tokens', null=True)),
                ('scraped_at', models.DateTimeField(auto_now_add=True)),
                ('company', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='scraped_data', to='core.company')),
            ],
        ),
        migrations.CreateModel(
            name='CompanyEmbedding',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('vector', pgvector.django.VectorField(dimensions=384)),
                ('umap_x', models.FloatField(blank=True, null=True)),
                ('umap_y', models.FloatField(blank=True, null=True)),
                ('cluster_id', models.IntegerField(blank=True, null=True)),
                ('cluster_label', models.CharField(blank=True, max_length=255, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('company', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='embedding', to='core.company')),
            ],
            options={
                'indexes': [
                    pgvector.django.HnswIndex(ef_construction=64, fields=['vector'], m=16, name='embedding_hnsw_idx', opclasses=['vector_cosine_ops']),
                ],
            },
        ),
    ]
