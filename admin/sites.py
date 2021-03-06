from django.conf.urls.defaults import patterns, include, url
from django.contrib import messages
from django.contrib.auth import authenticate, login, views as auth_views
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.models import User
from django.contrib.sites.models import Site
from django.core.mail import send_mail
from django.core.urlresolvers import reverse
from django.http import HttpResponseRedirect, Http404
from django.shortcuts import render_to_response, get_object_or_404
from django.template import RequestContext, loader
from django.utils.http import base36_to_int, int_to_base36
from django.utils.translation import ugettext_lazy, ugettext as _
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from stepping_out.auth.forms import PendUserCreationForm, TestHumanityForm
from stepping_out.auth.tokens import registration_token_generator, email_token_generator
from stepping_out.admin.admin import AdminSection
from stepping_out.admin.datastructures import OrderedDict
from stepping_out.mail.models import UserEmail
from django import forms


ERROR_MESSAGE = ugettext_lazy("Please enter a correct username and password. Note that both fields are case-sensitive.")
LOGIN_FORM_KEY = 'this_is_the_login_form'


LoginForm = type('LoginForm', (AuthenticationForm,), {LOGIN_FORM_KEY: forms.BooleanField(widget=forms.HiddenInput, initial=True)})


class AlreadyRegistered(Exception):
	pass


class NotRegistered(KeyError):
	pass


class AdminSite(object):
	url_prefix = 'stepping_out_admin'
	login_template = 'stepping_out/admin/login.html'
	logout_template = 'stepping_out/admin/logout.html'
	home_template = 'stepping_out/admin/home.html'
	account_create_template = 'stepping_out/registration/account_create.html'
	#account_create_done_template = 'stepping_out/registration/account_create_done.html'
	
	def __init__(self):
		self._registry = OrderedDict(key=lambda t: t[1].order)
	
	def register(self, section):
		"""
		Registers a given section with this AdminSite instance.
		"""
		if not issubclass(section, AdminSection):
			raise TypeError('%s must be a subclass of %s' %
				(section, AdminSection.__name__))
		
		if section.slug in self._registry:
			raise AlreadyRegistered('A section is already registered as %s.' %
				section.slug)
		
		self._registry[section.slug] = section(self)
	
	def get_section(self, slug):
		try:
			return self._registry[slug]
		except KeyError:
			raise NotRegistered("Module with slug '%s' not found in registry" % slug)
	
	@property
	def sections(self):
		return self._registry
	
	def has_permission(self, request):
		if request.user.is_authenticated() and request.user.is_active:
			return True
		
		return False
	
	def admin_view(self, view, cacheable=False):
		"""
		Decorator to apply common decorators to views for this admin.
		"""
		# FIXME: prohibit caching?
		def inner(request, *args, **kwargs):
			if not self.has_permission(request):
				return self.login(request, *args, **kwargs)
			return view(request, *args, **kwargs)
		inner = csrf_protect(inner)
		return inner
	
	def get_urls(self):
		def wrap(view, cacheable=False):
			return self.admin_view(view, cacheable) # (*args, **kwargs)
		
		urlpatterns = patterns('',
			url(r'^$', wrap(self.home), name='%s_root' % self.url_prefix),
			url(r'^logout/$', self.logout,
				name='%s_logout' % self.url_prefix),
		
			url(r'^password/reset/$', 'django.contrib.auth.views.password_reset',
				{'template_name': 'stepping_out/registration/password_reset_form.html'},
				name='%s_password_reset' % self.url_prefix),
			url(r'^password/reset/done/?$', auth_views.password_reset_done,
				{'template_name': 'stepping_out/registration/password_reset_done.html'},
				name='%s_password_reset_done' % self.url_prefix),
			url(r'^password/reset/complete/?$', auth_views.password_reset_complete,
				{'template_name': 'stepping_out/registration/password_reset_complete.html'},
				name='%s_password_reset_complete' % self.url_prefix),
			url(r'^password/reset/(?P<uidb36>\w+)/(?P<token>[^/]+)$', auth_views.password_reset_confirm,
				{'template_name': 'stepping_out/registration/password_reset_confirm.html'},
				name='%s_password_reset_confirm' % self.url_prefix),
			
			url(r'^create/$', self.account_create, name='%s_account_create' % self.url_prefix),
			#url(r'^create/done/$', self.account_create_done, name='%s_account_create_done' % self.url_prefix),
			url(r'^create/confirm/(?P<uidb36>\w+)-(?P<token>.+)/$', self.account_confirm, name='%s_account_confirm' % self.url_prefix),
			
			url(r'^emails/add/(?P<uidb36>\w+)-(?P<eidb36>\w+)-(?P<token>.+)/$', self.add_email, name='%s_email_add' % self.url_prefix)
		)
		
		for section in self._registry.values():
			urlpatterns += patterns('',
				url(r'^%s/' % section.slug, include(section.urls)),
			)
		
		return urlpatterns
	urls = property(get_urls)
	
	def get_context(self):
		return {}
	
	def get_nav(self, request):
		navbar = []
		for admin in self._registry.values():
			navbar += admin.get_nav(request)
		return navbar
	
	def home(self, request):
		try:
			return HttpResponseRedirect(self.get_section('home').get_root_url())
		except NotRegistered:
			return render_to_response(
				self.home_template,
				context_instance=RequestContext(request)
			)
		except:
			raise
	
	def display_login_form(self, request, message):
		request.session.set_test_cookie()
		if request.POST:
			form = LoginForm(request.POST)
		else:
			form = LoginForm()
		context = {
			'message': message,
			'form': form
		}
		return render_to_response(
			self.login_template,
			context,
			context_instance = RequestContext(request)
		)
	
	def login(self, request, *args, **kwargs):
		"""
		Displays the login form for the given HttpRequest.
		"""
		from django.contrib.auth.models import User
		
		# If this isn't already the login page, display it.
		if not request.POST.has_key(LOGIN_FORM_KEY):
			if request.POST:
				message = _("Please log in again, because your session has expired.")
			else:
				message = ""
			return self.display_login_form(request, message)

		# Check that the user accepts cookies.
		if not request.session.test_cookie_worked():
			message = _("Looks like your browser isn't configured to accept cookies. Please enable cookies, reload this page, and try again.")
			return self.display_login_form(request, message)
		else:
			request.session.delete_test_cookie()
		
		# Check the password.
		username = request.POST.get('username', None)
		password = request.POST.get('password', None)
		user = authenticate(username=username, password=password)
		if user is None:
			message = ERROR_MESSAGE
			if username is not None and u'@' in username:
				# Then they tried to log in with an email address and it failed.
				message = _("Please enter a correct email and password. Note that both fields are case-sensitive.")
			return self.display_login_form(request, message)

		# The user data is correct; log in the user in and continue.
		else:
			if user.is_active:
				login(request, user)
				return HttpResponseRedirect(request.get_full_path())
			else:
				return self.display_login_form(request, ERROR_MESSAGE)
	login = never_cache(login)
	
	def logout(self, request):
		from django.contrib.auth.views import logout
		defaults = {}
		if self.logout_template is not None:
			defaults['template_name'] = self.logout_template
		return logout(request, **defaults)
	
	def account_create(self, request, token_generator=registration_token_generator):
		if request.method == 'POST':
			form = PendUserCreationForm(request.POST)
			humanity_form = TestHumanityForm(request.POST)
			if form.is_valid():
				user = form.save()
				
				current_site = Site.objects.get_current()
				t = loader.get_template('stepping_out/registration/account_create_confirm_email.html')
				c = RequestContext(request, {
					'site': current_site,
					'protocol': 'http',
					'url': reverse('%s_account_confirm' % self.url_prefix, kwargs={'uidb36': int_to_base36(user.id), 'token': token_generator.make_token(user)})
				})
				# send an email!
				send_mail('Account confirmation link', t.render(c), 'noreply@%s' % current_site.domain, [user.email])
				
				messages.add_message(request, messages.SUCCESS, 'Account created. An email has been sent to the address you provided detailing how to activate your account.')
				return HttpResponseRedirect('')
		else:
			form = PendUserCreationForm()
			humanity_form = TestHumanityForm()
		
		c = {
			'form': form,
			'humanity_form': humanity_form
		}
		c.update(self.get_context(request))
		return render_to_response(self.account_create_template, c,
			context_instance=RequestContext(request))
	
	def account_confirm(self, request, uidb36=None, token=None, token_generator=registration_token_generator):
		assert uidb36 is not None and token is not None
		
		try:
			uid_int = base36_to_int(uidb36)
		except ValueError:
			raise Http404
		
		user = get_object_or_404(User, id=uid_int)
		if token_generator.check_token(user, token):
			user.is_active = True
			
			# Set up their first useremail before save so that nasty things
			# don't happen w/ the autosyncing.
			useremail = UserEmail.objects.get_or_create(email=user.email)[0]
			useremail.user = user
			useremail.save()
			
			true_password = user.password
			try:
				user.set_password('tmp')
				user.save()
				user = authenticate(username=user.username, password='tmp')
				login(request, user)
				messages.add_message(request, messages.SUCCESS, "Your account's been activated! Welcome!")
			except:
				messages.add_message(request, messages.SUCCESS, "Your account's been activated! Go ahead and log in!")
			finally:
				# to make sure the true password is returned to its rightful place.
				user.password = true_password
				user.save()
			
			return HttpResponseRedirect(reverse('%s_root' % self.url_prefix))
		
		# Should there be a pretty "link expired" page?
		raise Http404
	
	def add_email(self, request, uidb36=None, eidb36=None, token=None, token_generator=email_token_generator):
		assert uidb36 is not None and eidb36 is not None and token is not None
		
		try:
			uid_int = base36_to_int(uidb36)
			eid_int = base36_to_int(eidb36)
		except ValueError:
			raise Http404
		
		user = get_object_or_404(User, id=uid_int)
		email = get_object_or_404(UserEmail, id=eid_int)
		
		if token_generator.check_token(user, email, token):
			email.user = user
			email.save()
			messages.add_message(request, messages.SUCCESS, 'Email added successfully.')
			return HttpResponseRedirect(reverse('%s_root' % self.url_prefix))
		
		raise Http404

site = AdminSite()