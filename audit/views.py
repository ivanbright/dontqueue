from django.views.generic import ListView

from core.permissions import OrganizationAccessMixin

from .models import AuditLog


class AuditLogListView(OrganizationAccessMixin, ListView):
    template_name = "audit/log.html"
    admin_required = True
    context_object_name = "logs"
    paginate_by = 50

    def get_queryset(self):
        return AuditLog.objects.filter(organization=self.organization).select_related("actor")
