from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import Fixture, CustomUser
# Register your models here.


@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    model = CustomUser
    ordering = ('email',)
    list_display = ('email', 'username', 'auth_provider', 'email_verified', 'is_staff', 'is_active')
    list_filter = ('auth_provider', 'email_verified', 'is_staff', 'is_active')
    search_fields = ('email', 'username', 'first_name', 'last_name', 'google_id')
    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        ('Profile', {'fields': ('username', 'first_name', 'last_name', 'avatar_url', 'credit')}),
        ('Social auth', {'fields': ('auth_provider', 'google_id', 'email_verified')}),
        ('Sign-in details', {'fields': ('signup_ip', 'last_login_ip', 'last_login', 'date_joined', 'updated_at')}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser', 'is_admin', 'groups', 'user_permissions')}),
    )
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'password1', 'password2', 'is_staff', 'is_active'),
        }),
    )
    readonly_fields = ('last_login', 'date_joined', 'updated_at')


admin.site.register(Fixture)
