from django.db import models


class Service(models.Model):
    code = models.CharField(max_length=255, unique=True)
    section_code = models.CharField(max_length=150)
    name = models.CharField(max_length=255)
    description = models.TextField()
    form_schema = models.JSONField()
    pricing_config = models.JSONField()
    is_active = models.BooleanField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'services'
        ordering = ['section_code', 'name']

    def __str__(self):
        return self.name


class ServiceImage(models.Model):
    service = models.ForeignKey(Service, on_delete=models.DO_NOTHING, related_name='images')
    image = models.CharField(max_length=255)
    alt_text = models.CharField(max_length=255, blank=True, null=True)
    sort_order = models.IntegerField(default=0)
    is_primary = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'service_images'
        constraints = [
            models.CheckConstraint(
                condition=models.Q(sort_order__gte=0),
                name='service_images_sort_order_check',
            ),
        ]
        ordering = ['-is_primary', 'sort_order', 'id']

    def __str__(self):
        return f"{self.service} - {self.image}"
