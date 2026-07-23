# main/context_processors.py
from django.conf import settings


def google_analytics(request):
    return {'GA_MEASUREMENT_ID': settings.GA_MEASUREMENT_ID}
