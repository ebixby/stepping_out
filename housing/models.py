from django.contrib.auth.models import User
from django.contrib.contenttypes import generic
from django.contrib.contenttypes.models import ContentType
from django.db import models


NEUTRAL = '0'
REQUESTED = '1'
OFFERED = '2'
HOUSING_CHOICES = (
	(NEUTRAL, "I do not need housing and I can't offer housing"),
	(REQUESTED, "I need housing"),
	(OFFERED, "I can offer housing"),
)


class OfferedHousing(models.Model):
	coordinator = models.ForeignKey('HousingCoordinator', related_name='offered_housing')
	user = models.ForeignKey(User)
	address = models.TextField()
	smoking = models.BooleanField(verbose_name='Smoking or recent smoking')
	cats = models.BooleanField()
	dogs = models.BooleanField()
	num_ideal = models.PositiveIntegerField(verbose_name='Ideal number of guests')
	num_max = models.PositiveIntegerField(verbose_name='Maximum number of guests')
	comments = models.TextField(verbose_name='Additional comments', blank=True)
	
	class Meta:
		app_label = 'stepping_out'
		verbose_name = "Housing Offer"
		verbose_name_plural = "Offered Housing"
		unique_together = ['coordinator', 'user']


class RequestedHousing(models.Model):
	user = models.ForeignKey(User)
	coordinator = models.ForeignKey('HousingCoordinator', related_name='requested_housing')
	PREFERENCE_CHOICES = (
		(0, "I don't care"),
		(1, "Preferred"),
		(2, "A must!"),
	)
	nonsmoking = models.IntegerField(max_length=1, choices=PREFERENCE_CHOICES)
	no_cats = models.IntegerField(max_length=1, choices=PREFERENCE_CHOICES)
	no_dogs =  models.IntegerField(max_length=1, choices=PREFERENCE_CHOICES)
	housed_with = models.ForeignKey(OfferedHousing, blank=True, null=True, related_name='housed')
	comments = models.TextField(verbose_name='Additional comments', blank=True)
	
	class Meta:
		app_label = 'stepping_out'
		verbose_name = "Housing Request"
		verbose_name_plural = "Requested Housing"


class HousingCoordinator(models.Model):
	offering_users = models.ManyToManyField(User, through=OfferedHousing, related_name='housing_coordinator_offered_set')
	requesting_users = models.ManyToManyField(User, through=RequestedHousing, related_name='housing_coordinator_requested_set')
	event_content_type = models.ForeignKey(ContentType, blank=True, null=True)
	event_object_id = models.PositiveIntegerField(blank=True, null=True)
	event = generic.GenericForeignKey('event_content_type', 'event_object_id')
	
	def get_housing_status(self, user):
		if self.requesting_users.filter(pk=user.pk):
			return REQUESTED
		elif self.offering_users.filter(pk=user.pk):
			return OFFERED
		
		return NEUTRAL
	
	class Meta:
		app_label = 'stepping_out'
		unique_together = ('event_content_type', 'event_object_id')