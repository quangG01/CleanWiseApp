from rest_framework import generics, status
from rest_framework.parsers import (
    MultiPartParser,
    FormParser,
    JSONParser,
)
from rest_framework.response import Response

from .models import (
    ServiceCategory,
    Service,
    ServicePackage,
)

from .serializers import (
    ServiceCategorySerializer,
    ServiceListSerializer,
    ServiceDetailSerializer,
    ServiceWriteSerializer,
    ServicePackageSerializer,
)

from .permissions import IsAdminOrReadOnly

from .schemas import (
    SERVICE_CATEGORY_LIST_SCHEMA,
    SERVICE_CATEGORY_DETAIL_SCHEMA,
    SERVICE_LIST_SCHEMA,
    SERVICE_DETAIL_SCHEMA,
    SERVICE_PACKAGE_LIST_SCHEMA,
)


# ======================================================================================================================
# SERVICE CATEGORY
# ======================================================================================================================

@SERVICE_CATEGORY_LIST_SCHEMA
class ServiceCategoryListCreateView(
    generics.ListCreateAPIView
):

    serializer_class = ServiceCategorySerializer

    permission_classes = [
        IsAdminOrReadOnly
    ]

    parser_classes = [
        MultiPartParser,
        FormParser,
        JSONParser,
    ]

    def get_queryset(self):

        queryset = ServiceCategory.objects.all()

        is_active = self.request.query_params.get(
            "is_active"
        )

        if is_active is not None:

            queryset = queryset.filter(
                is_active=is_active.lower() == "true"
            )

        return queryset

    def create(
        self,
        request,
        *args,
        **kwargs,
    ):

        serializer = self.get_serializer(
            data=request.data
        )

        serializer.is_valid(
            raise_exception=True
        )

        category = serializer.save()

        return Response(
            {
                "message": (
                    "Tạo danh mục dịch vụ "
                    "thành công."
                ),
                "data": ServiceCategorySerializer(
                    category
                ).data,
            },
            status=status.HTTP_201_CREATED,
        )


# ======================================================================================================================
# SERVICE CATEGORY DETAIL
# ======================================================================================================================

@SERVICE_CATEGORY_DETAIL_SCHEMA
class ServiceCategoryDetailView(
    generics.RetrieveUpdateAPIView
):

    queryset = ServiceCategory.objects.all()

    serializer_class = ServiceCategorySerializer

    permission_classes = [
        IsAdminOrReadOnly
    ]

    parser_classes = [
        MultiPartParser,
        FormParser,
        JSONParser,
    ]

    def patch(
        self,
        request,
        *args,
        **kwargs,
    ):

        instance = self.get_object()

        serializer = self.get_serializer(
            instance,
            data=request.data,
            partial=True,
        )

        serializer.is_valid(
            raise_exception=True
        )

        category = serializer.save()

        return Response(
            {
                "message": (
                    "Cập nhật danh mục dịch vụ "
                    "thành công."
                ),
                "data": ServiceCategorySerializer(
                    category
                ).data,
            },
            status=status.HTTP_200_OK,
        )


# ======================================================================================================================
# SERVICE
# ======================================================================================================================

@SERVICE_LIST_SCHEMA
class ServiceListCreateView(
    generics.ListCreateAPIView
):

    permission_classes = [
        IsAdminOrReadOnly
    ]

    parser_classes = [
        MultiPartParser,
        FormParser,
        JSONParser,
    ]

    def get_serializer_class(self):

        if self.request.method == "POST":
            return ServiceWriteSerializer

        return ServiceListSerializer

    def get_queryset(self):

        queryset = (
            Service.objects
            .select_related("category")
            .prefetch_related("images")
        )

        params = self.request.query_params

        category_id = params.get(
            "category_id"
        )

        if category_id:

            queryset = queryset.filter(
                category_id=category_id
            )

        is_active = params.get(
            "is_active"
        )

        if is_active is not None:

            queryset = queryset.filter(
                is_active=is_active.lower() == "true"
            )

        search = params.get(
            "search"
        )

        if search:

            queryset = queryset.filter(
                name__icontains=search
            )

        return queryset

    def list(
        self,
        request,
        *args,
        **kwargs,
    ):

        queryset = self.get_queryset()

        page = self.paginate_queryset(
            queryset
        )

        if page is not None:

            serializer = self.get_serializer(
                page,
                many=True,
            )

            return self.get_paginated_response(
                serializer.data
            )

        serializer = self.get_serializer(
            queryset,
            many=True,
        )

        return Response(
            {
                "results": serializer.data
            },
            status=status.HTTP_200_OK,
        )

    def create(
        self,
        request,
        *args,
        **kwargs,
    ):

        serializer = self.get_serializer(
            data=request.data
        )

        serializer.is_valid(
            raise_exception=True
        )

        service = serializer.save()

        return Response(
            {
                "message": (
                    "Tạo dịch vụ thành công."
                ),
                "data": ServiceDetailSerializer(
                    service
                ).data,
            },
            status=status.HTTP_201_CREATED,
        )


# ======================================================================================================================
# SERVICE DETAIL
# ======================================================================================================================

@SERVICE_DETAIL_SCHEMA
class ServiceDetailView(
    generics.RetrieveUpdateAPIView
):

    queryset = (
        Service.objects
        .select_related("category")
        .prefetch_related(
            "images",
            "packages",
        )
    )

    permission_classes = [
        IsAdminOrReadOnly
    ]

    parser_classes = [
        MultiPartParser,
        FormParser,
        JSONParser,
    ]

    def get_serializer_class(self):

        if self.request.method in (
            "PATCH",
            "PUT",
        ):
            return ServiceWriteSerializer

        return ServiceDetailSerializer

    def retrieve(
        self,
        request,
        *args,
        **kwargs,
    ):

        instance = self.get_object()

        serializer = ServiceDetailSerializer(
            instance
        )

        return Response(
            {
                "data": serializer.data
            },
            status=status.HTTP_200_OK,
        )

    def patch(
        self,
        request,
        *args,
        **kwargs,
    ):

        instance = self.get_object()

        serializer = self.get_serializer(
            instance,
            data=request.data,
            partial=True,
        )

        serializer.is_valid(
            raise_exception=True
        )

        service = serializer.save()

        return Response(
            {
                "message": (
                    "Cập nhật dịch vụ "
                    "thành công."
                ),
                "data": ServiceDetailSerializer(
                    service
                ).data,
            },
            status=status.HTTP_200_OK,
        )


# ======================================================================================================================
# SERVICE PACKAGE
# ======================================================================================================================

@SERVICE_PACKAGE_LIST_SCHEMA
class ServicePackageListCreateView(
    generics.ListCreateAPIView
):

    serializer_class = ServicePackageSerializer

    permission_classes = [
        IsAdminOrReadOnly
    ]

    def get_queryset(self):

        return ServicePackage.objects.filter(
            service_id=self.kwargs[
                "service_id"
            ]
        )

    def create(
        self,
        request,
        *args,
        **kwargs,
    ):

        serializer = self.get_serializer(
            data=request.data
        )

        serializer.is_valid(
            raise_exception=True
        )

        package = serializer.save(
            service_id=self.kwargs[
                "service_id"
            ]
        )

        return Response(
            {
                "message": (
                    "Tạo gói dịch vụ "
                    "thành công."
                ),
                "data": ServicePackageSerializer(
                    package
                ).data,
            },
            status=status.HTTP_201_CREATED,
        )
