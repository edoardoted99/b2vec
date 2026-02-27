from django.db import models

class Company(models.Model):
    SCRAPE_STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('success', 'Success'),
        ('error', 'Error'),
    ]

    # CSV fields
    handle = models.CharField(max_length=512, unique=True, null=True, blank=True)
    name = models.CharField(max_length=255)
    url = models.URLField(blank=True, null=True)
    website = models.CharField(max_length=255, blank=True, null=True, help_text="Raw domain from CSV")
    industry = models.CharField(max_length=255, blank=True, null=True)
    size = models.CharField(max_length=50, blank=True, null=True)
    type = models.CharField(max_length=100, blank=True, null=True)
    founded = models.CharField(max_length=10, blank=True, null=True)
    city = models.CharField(max_length=255, blank=True, null=True)
    state = models.CharField(max_length=255, blank=True, null=True)
    country_code = models.CharField(max_length=10, blank=True, null=True)

    # Scrape tracking
    scrape_status = models.CharField(max_length=10, choices=SCRAPE_STATUS_CHOICES, default='pending')
    scrape_error_type = models.CharField(max_length=50, blank=True, null=True)
    scrape_error_detail = models.TextField(blank=True, null=True)
    scraped_at = models.DateTimeField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

class ScrapedData(models.Model):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='scraped_data')
    text_content = models.TextField(help_text="Raw text content from the website")
    cleaned_content = models.TextField(help_text="Preprocessed logical tokens", blank=True, null=True)
    scraped_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Scraped data for {self.company.name}"

class CompanyEmbedding(models.Model):
    company = models. OneToOneField(Company, on_delete=models.CASCADE, related_name='embedding')
    vector = models.JSONField(help_text="High-dimensional vector")
    embedding_method = models.CharField(max_length=50, default="word2vec_avg")
    pca_x = models.FloatField(help_text="X coordinate for 2D visualization", blank=True, null=True)
    pca_y = models.FloatField(help_text="Y coordinate for 2D visualization", blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Embedding for {self.company.name}"
