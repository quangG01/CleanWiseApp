from django.conf import settings
from django.db import models


class Review(models.Model):
    assignment = models.OneToOneField(
        'worker.BookingAssignment',
        on_delete=models.PROTECT,
        related_name='review',
    )
    rating = models.IntegerField()
    comment = models.TextField(blank=True, null=True)
    admin_reply = models.TextField(blank=True, null=True)
    replied_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.DO_NOTHING, related_name='review_replies', blank=True, null=True)
    replied_at = models.DateTimeField(blank=True, null=True)
    is_visible = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'reviews'
        constraints = [models.CheckConstraint(condition=models.Q(rating__gte=1) & models.Q(rating__lte=5), name='reviews_rating_check')]
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.assignment} - {self.rating}'


class ReviewImage(models.Model):
    review = models.ForeignKey(Review, on_delete=models.DO_NOTHING, related_name='images')
    image = models.CharField(max_length=255)
    caption = models.CharField(max_length=255, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'review_images'
        ordering = ['created_at', 'id']

    def __str__(self):
        return f'{self.review} - {self.image}'
