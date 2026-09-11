from django.urls import path

from .views import (
    ServiceCategoryListCreateView,
    ServiceCategoryDetailView,
    ServiceListCreateView,
    ServiceDetailView,
    ServicePackageListCreateView,
)


urlpatterns = [

    # =================================================================
    # SERVICE CATEGORY
    # =================================================================

    path(
        "categories/",
        ServiceCategoryListCreateView.as_view(),
        name="service-category-list",
    ),

    path(
        "categories/<int:pk>/",
        ServiceCategoryDetailView.as_view(),
        name="service-category-detail",
    ),


    # =================================================================
    # SERVICE
    # =================================================================

    path(
        "",
        ServiceListCreateView.as_view(),
        name="service-list",
    ),

    path(
        "<int:pk>/",
        ServiceDetailView.as_view(),
        name="service-detail",
    ),


    # =================================================================
    # SERVICE PACKAGE
    # =================================================================

    path(
        "<int:service_id>/packages/",
        ServicePackageListCreateView.as_view(),
        name="service-package-list",
    ),
]
