"""OAuth utility functions."""

import logging
from datetime import datetime

from allauth.socialaccount.models import SocialAccount
from allauth.socialaccount.providers import registry
from django.conf import settings
from django.utils import timezone
from oauthlib.oauth2.rfc6749.errors import InvalidClientIdError
from requests.exceptions import RequestException
from requests_oauthlib import OAuth2Session

from readthedocs.oauth.models import RemoteRepositoryRelation


log = logging.getLogger(__name__)


class SyncServiceError(Exception):

    """Error raised when a service failed to sync."""

    pass


class Service:

    """
    Service mapping for local accounts.

    :param user: User to use in token lookup and session creation
    :param account: :py:class:`SocialAccount` instance for user
    """

    adapter = None
    url_pattern = None

    default_user_avatar_url = settings.OAUTH_AVATAR_USER_DEFAULT_URL
    default_org_avatar_url = settings.OAUTH_AVATAR_ORG_DEFAULT_URL

    def __init__(self, user, account):
        self.session = None
        self.user = user
        self.account = account

    @classmethod
    def for_user(cls, user):
        """Return list of instances if user has an account for the provider."""
        try:
            accounts = SocialAccount.objects.filter(
                user=user,
                provider=cls.adapter.provider_id,
            )
            return [cls(user=user, account=account) for account in accounts]
        except SocialAccount.DoesNotExist:
            return []

    def get_adapter(self):
        return self.adapter

    @property
    def provider_id(self):
        return self.get_adapter().provider_id

    @property
    def provider_name(self):
        return registry.by_id(self.provider_id).name

    def get_session(self):
        if self.session is None:
            self.create_session()
        return self.session

    def create_session(self):
        """
        Create OAuth session for user.

        This configures the OAuth session based on the :py:class:`SocialToken`
        attributes. If there is an ``expires_at``, treat the session as an auto
        renewing token. Some providers expire tokens after as little as 2 hours.
        """
        token = self.account.socialtoken_set.first()
        if token is None:
            return None

        token_config = {
            'access_token': token.token,
            'token_type': 'bearer',
        }
        if token.expires_at is not None:
            token_expires = (token.expires_at - timezone.now()).total_seconds()
            token_config.update({
                'refresh_token': token.token_secret,
                'expires_in': token_expires,
            })

        self.session = OAuth2Session(
            client_id=token.app.client_id,
            token=token_config,
            auto_refresh_kwargs={
                'client_id': token.app.client_id,
                'client_secret': token.app.secret,
            },
            auto_refresh_url=self.get_adapter().access_token_url,
            token_updater=self.token_updater(token),
        )

        return self.session or None

    def token_updater(self, token):
        """
        Update token given data from OAuth response.

        Expect the following response into the closure::

            {
                u'token_type': u'bearer',
                u'scopes': u'webhook repository team account',
                u'refresh_token': u'...',
                u'access_token': u'...',
                u'expires_in': 3600,
                u'expires_at': 1449218652.558185
            }
        """

        def _updater(data):
            token.token = data['access_token']
            token.expires_at = timezone.make_aware(
                datetime.fromtimestamp(data['expires_at']),
            )
            token.save()
            log.info('Updated token %s:', token)

        return _updater

    def paginate(self, url, **kwargs):
        """
        Recursively combine results from service's pagination.

        :param url: start url to get the data from.
        :type url: unicode
        :param kwargs: optional parameters passed to .get() method
        :type kwargs: dict
        """
        try:
            resp = self.get_session().get(url, data=kwargs)

            # TODO: this check of the status_code would be better in the
            # ``create_session`` method since it could be used from outside, but
            # I didn't find a generic way to make a test request to each
            # provider.
            if resp.status_code == 401:
                # Bad credentials: the token we have in our database is not
                # valid. Probably the user has revoked the access to our App. He
                # needs to reconnect his account
                raise SyncServiceError(
                    'Our access to your {provider} account was revoked. '
                    'Please, reconnect it from your social account connections.'.format(
                        provider=self.provider_name,
                    ),
                )

            next_url = self.get_next_url_to_paginate(resp)
            results = self.get_paginated_results(resp)
            if next_url:
                results.extend(self.paginate(next_url))
            return results
        # Catch specific exception related to OAuth
        except InvalidClientIdError:
            log.warning('access_token or refresh_token failed: %s', url)
            raise Exception('You should reconnect your account')
        # Catch exceptions with request or deserializing JSON
        except (RequestException, ValueError):
            # Response data should always be JSON, still try to log if not
            # though
            try:
                debug_data = resp.json()
            except ValueError:
                debug_data = resp.content
            log.debug(
                'Paginate failed at %s with response: %s',
                url,
                debug_data,
            )

        return []

    def sync(self):
        """
        Sync repositories (RemoteRepository) and organizations (RemoteOrganization).

        - creates a new RemoteRepository/Organization per new repository
        - updates fields for existing RemoteRepository/Organization
        - deletes old RemoteRepository/Organization that are not present
          for this user in the current provider
        """
        remote_repositories = self.sync_repositories()
        remote_organizations, remote_repositories_organizations = self.sync_organizations()

        # Delete RemoteRepository where the user doesn't have access anymore
        # (skip RemoteRepository tied to a Project on this user)
        all_remote_repositories = remote_repositories + remote_repositories_organizations
        repository_full_names = [r.full_name for r in all_remote_repositories if r is not None]
        (
            self.user.remote_repository_relations
            .exclude(remoterepository__full_name__in=repository_full_names)
            .filter(account=self.account)
            .delete()
        )

        # Delete RemoteOrganization where the user doesn't have access anymore
        organization_slugs = [o.slug for o in remote_organizations if o is not None]
        (
            self.user.oauth_organizations
            .exclude(slug__in=organization_slugs)
            .filter(account=self.account)
            .delete()
        )

    def get_remote_repository_relation(self, repo):
        """Return RemoteRepositoryRelation object for a given remote repository."""
        remote_repository_relation, _ = (
            RemoteRepositoryRelation.objects.get_or_create(
                remoterepository=repo,
                user=self.user,
                account=self.account
            )
        )
        return remote_repository_relation

    def create_repository(self, fields, privacy=None, organization=None):
        """
        Update or create a repository from API response.

        :param fields: dictionary of response data from API
        :param privacy: privacy level to support
        :param organization: remote organization to associate with
        :type organization: RemoteOrganization
        :rtype: RemoteRepository
        """
        raise NotImplementedError

    def create_organization(self, fields):
        """
        Update or create remote organization from API response.

        :param fields: dictionary response of data from API
        :rtype: RemoteOrganization
        """
        raise NotImplementedError

    def get_next_url_to_paginate(self, response):
        """
        Return the next url to feed the `paginate` method.

        :param response: response from where to get the `next_url` attribute
        :type response: requests.Response
        """
        raise NotImplementedError

    def get_paginated_results(self, response):
        """
        Return the results for the current response/page.

        :param response: response from where to get the results.
        :type response: requests.Response
        """
        raise NotImplementedError

    def get_provider_data(self, project, integration):
        """
        Gets provider data from Git Providers Webhooks API.

        :param project: project
        :type project: Project
        :param integration: Integration for the project
        :type integration: Integration
        :returns: Dictionary containing provider data from the API or None
        :rtype: dict
        """
        raise NotImplementedError

    def setup_webhook(self, project, integration=None):
        """
        Setup webhook for project.

        :param project: project to set up webhook for
        :type project: Project
        :param integration: Integration for the project
        :type integration: Integration
        :returns: boolean based on webhook set up success, and requests Response object
        :rtype: (Bool, Response)
        """
        raise NotImplementedError

    def update_webhook(self, project, integration):
        """
        Update webhook integration.

        :param project: project to set up webhook for
        :type project: Project
        :param integration: Webhook integration to update
        :type integration: Integration
        :returns: boolean based on webhook update success, and requests Response object
        :rtype: (Bool, Response)
        """
        raise NotImplementedError

    def send_build_status(self, build, commit, state, link_to_build=False):
        """
        Create commit status for project.

        :param build: Build to set up commit status for
        :type build: Build
        :param commit: commit sha of the pull/merge request
        :type commit: str
        :param state: build state failure, pending, or success.
        :type state: str
        :param link_to_build: If true, link to the build page regardless the state.
        :returns: boolean based on commit status creation was successful or not.
        :rtype: Bool
        """
        raise NotImplementedError

    @classmethod
    def is_project_service(cls, project):
        """
        Determine if this is the service the project is using.

        .. note::

            This should be deprecated in favor of attaching the
            :py:class:`RemoteRepository` to the project instance. This is a
            slight improvement on the legacy check for webhooks
        """
        # TODO Replace this check by keying project to remote repos
        return (
            cls.url_pattern is not None and
            cls.url_pattern.search(project.repo) is not None
        )
