from django.urls import path, include
from . import views
from .views import AllLeaguesPrediction


urlpatterns = [
    path('', views.home, name="home"),
    path('fixture/<str:fixture_id>/', views.fixture_details, name="fixture_details"),
    path('all/', AllLeaguesPrediction.as_view(), name="all_leagues_prediction"),
]
