import json

from django.core.urlresolvers import reverse
from django.test import TestCase
from django.test.client import RequestFactory

from basket import errors
from mock import ANY, Mock, patch

from news import models, views
from news.models import APIUser, Newsletter
from news.newsletters import newsletter_languages, newsletter_fields
from news.views import language_code_is_valid, get_accept_languages, get_best_language


none_mock = Mock(return_value=None)


@patch('news.views.update_fxa_info')
class FxAccountsTest(TestCase):
    def ssl_post(self, url, params=None, **extra):
        """Fake a post that used SSL"""
        extra['wsgi.url_scheme'] = 'https'
        params = params or {}
        return self.client.post(url, data=params, **extra)

    def test_requires_ssl(self, fxa_mock):
        """fxa-register requires SSL"""
        resp = self.client.post('/news/fxa-register/', {
            'email': 'dude@example.com',
            'fxa_id': 'the dude has a Fx account.',
            'accept_lang': 'de',
        })
        self.assertEqual(resp.status_code, 401, resp.content)
        data = json.loads(resp.content)
        self.assertEqual(errors.BASKET_SSL_REQUIRED, data['code'])
        self.assertFalse(fxa_mock.delay.called)

    def test_requires_api_key(self, fxa_mock):
        """fxa-register requires API key"""
        # Use SSL but no API key
        resp = self.ssl_post('/news/fxa-register/', {
            'email': 'dude@example.com',
            'fxa_id': 'the dude has a Fx account.'
        })
        self.assertEqual(resp.status_code, 401, resp.content)
        data = json.loads(resp.content)
        self.assertEqual(errors.BASKET_AUTH_ERROR, data['code'])
        self.assertFalse(fxa_mock.delay.called)

    def test_requires_fxa_id(self, fxa_mock):
        """fxa-register requires Firefox Account ID"""
        auth = APIUser.objects.create(name="test")
        resp = self.ssl_post('/news/fxa-register/', {
            'email': 'dude@example.com',
            'accept_lang': 'de',
            'api-key': auth.api_key,
        })
        self.assertEqual(resp.status_code, 401, resp.content)
        data = json.loads(resp.content)
        self.assertEqual(errors.BASKET_USAGE_ERROR, data['code'])
        self.assertFalse(fxa_mock.delay.called)

    def test_requires_email(self, fxa_mock):
        """fxa-register requires email address"""
        auth = APIUser.objects.create(name="test")
        resp = self.ssl_post('/news/fxa-register/', {
            'fxa_id': 'the dude has a Fx account.',
            'accept_lang': 'de',
            'api-key': auth.api_key,
        })
        self.assertEqual(resp.status_code, 401, resp.content)
        data = json.loads(resp.content)
        self.assertEqual(errors.BASKET_USAGE_ERROR, data['code'])
        self.assertFalse(fxa_mock.delay.called)

    def test_requires_lang(self, fxa_mock):
        """fxa-register requires language"""
        auth = APIUser.objects.create(name="test")
        resp = self.ssl_post('/news/fxa-register/', {
            'email': 'dude@example.com',
            'fxa_id': 'the dude has a Fx account.',
            'api-key': auth.api_key,
        })
        self.assertEqual(resp.status_code, 401, resp.content)
        data = json.loads(resp.content)
        self.assertEqual(errors.BASKET_USAGE_ERROR, data['code'])
        self.assertFalse(fxa_mock.delay.called)

    def test_requires_valid_lang(self, fxa_mock):
        """fxa-register requires language"""
        auth = APIUser.objects.create(name="test")
        resp = self.ssl_post('/news/fxa-register/', {
            'email': 'dude@example.com',
            'fxa_id': 'the dude has a Fx account.',
            'accept_lang': 'Phones ringing Dude.',
            'api-key': auth.api_key,
        })
        self.assertEqual(resp.status_code, 400, resp.content)
        data = json.loads(resp.content)
        self.assertEqual(errors.BASKET_INVALID_LANGUAGE, data['code'])
        self.assertFalse(fxa_mock.delay.called)

    def test_with_ssl_and_api_key(self, fxa_mock):
        """fxa-register should succeed with SSL, API Key, and data."""
        auth = APIUser.objects.create(name="test")
        request_data = {
            'email': 'dude@example.com',
            'fxa_id': 'the dude has a Fx account.',
            'api-key': auth.api_key,
            'accept_lang': 'de',
        }
        resp = self.ssl_post('/news/fxa-register/', request_data)
        self.assertEqual(resp.status_code, 200, resp.content)
        data = json.loads(resp.content)
        self.assertEqual('ok', data['status'])
        fxa_mock.delay.assert_called_once_with(request_data['email'], 'de',
                                               request_data['fxa_id'])


class TestGetAcceptLanguages(TestCase):
    # mostly stolen from bedrock

    def setUp(self):
        patcher = patch('news.views.newsletter_languages', return_value=[
            'de', 'en', 'es', 'fr', 'id', 'pt-BR', 'ru', 'pl', 'hu'])
        self.addCleanup(patcher.stop)
        patcher.start()

    def _test(self, accept_lang, good_list):
        self.assertListEqual(get_accept_languages(accept_lang), good_list)

    def test_valid_lang_codes(self):
        """
        Should return a list of valid lang codes
        """
        self._test('fr-FR', ['fr'])
        self._test('en-us,en;q=0.5', ['en'])
        self._test('pt-pt,fr;q=0.8,it-it;q=0.5,de;q=0.3',
                   ['pt-PT', 'fr', 'it-IT', 'de'])
        self._test('ja-JP-mac,ja-JP;q=0.7,ja;q=0.3', ['ja-JP', 'ja'])
        self._test('foo,bar;q=0.5', ['foo', 'bar'])

    def test_invalid_lang_codes(self):
        """
        Should return a list of valid lang codes or an empty list
        """
        self._test('', [])
        self._test('en_us,en*;q=0.5', [])
        self._test('Chinese,zh-cn;q=0.5', ['zh-CN'])


class GetBestLanguageTests(TestCase):
    def setUp(self):
        patcher = patch('news.views.newsletter_languages', return_value=[
            'de', 'en', 'es', 'fr', 'id', 'pt-BR', 'ru', 'pl', 'hu'])
        self.addCleanup(patcher.stop)
        patcher.start()

    def _test(self, langs_list, expected_lang):
        self.assertEqual(get_best_language(langs_list), expected_lang)

    def test_returns_first_good_lang(self):
        """Should return first language in the list that a newsletter supports."""
        self._test(['zh-TW', 'es', 'de', 'en'], 'es')
        self._test(['pt-PT', 'zh-TW', 'pt-BR', 'en'], 'pt-BR')

    def test_returns_first_lang_no_good(self):
        """Should return the first in the list if no supported are found."""
        self._test(['pt-PT', 'zh-TW', 'zh-CN', 'ar'], 'pt-PT')

    def test_no_langs(self):
        """Should return none if no langs given."""
        self._test([], None)


class SubscribeEmailValidationTest(TestCase):
    email = 'dude@example.com'
    data = {
        'email': email,
        'newsletters': 'os',
    }
    view = 'subscribe'

    def setUp(self):
        self.rf = RequestFactory()

    @patch('news.views.validate_email')
    def test_invalid_email(self, mock_validate):
        """Should return proper error for invalid email."""
        mock_validate.side_effect = views.EmailValidationError('Invalid email')
        view = getattr(views, self.view)
        resp = view(self.rf.post('/', self.data))
        resp_data = json.loads(resp.content)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp_data['status'], 'error')
        self.assertEqual(resp_data['code'], errors.BASKET_INVALID_EMAIL)
        self.assertNotIn('suggestion', resp_data)

    @patch('news.views.validate_email')
    def test_invalid_email_suggestion(self, mock_validate):
        """Should return proper error for invalid email."""
        mock_validate.side_effect = views.EmailValidationError('Invalid email',
                                                               'walter@example.com')
        view = getattr(views, self.view)
        resp = view(self.rf.post('/', self.data))
        resp_data = json.loads(resp.content)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp_data['status'], 'error')
        self.assertEqual(resp_data['code'], errors.BASKET_INVALID_EMAIL)
        self.assertEqual(resp_data['suggestion'], 'walter@example.com')


class RecoveryMessageEmailValidationTest(SubscribeEmailValidationTest):
    view = 'send_recovery_message'


@patch('news.views.validate_email', none_mock)
class SubscribeTest(TestCase):
    def setUp(self):
        kwargs = {
            "vendor_id": "MOZILLA_AND_YOU",
            "description": "A monthly newsletter packed with tips to "
                           "improve your browsing experience.",
            "show": True,
            "welcome": "",
            "languages": "de,en,es,fr,id,pt-BR,ru",
            "active": True,
            "title": "Firefox & You",
            "slug": "mozilla-and-you"
        }
        Newsletter.objects.create(**kwargs)

    def ssl_post(self, url, params=None, **extra):
        """Fake a post that used SSL"""
        extra['wsgi.url_scheme'] = 'https'
        params = params or {}
        return self.client.post(url, data=params, **extra)

    def test_cors_header(self):
        """Should return Access-Control-Allow-Origin header."""
        resp = self.client.post('/news/subscribe/', {
            'email': 'dude@example.com',
        }, HTTP_ORIGIN='http://example.com')
        self.assertEqual(resp['Access-Control-Allow-Origin'], '*')

    def test_no_newsletters_error(self):
        """
        Should return an error and not create a subscriber if
        no newsletters were specified.
        """
        resp = self.client.post('/news/subscribe/', {
            'email': 'dude@example.com',
        })
        self.assertEqual(resp.status_code, 400)
        data = json.loads(resp.content)
        self.assertEqual(data['status'], 'error')
        self.assertEqual(data['desc'], 'newsletters is missing')
        with self.assertRaises(models.Subscriber.DoesNotExist):
            models.Subscriber.objects.get(email='dude@example.com')

        resp = self.client.post('/news/subscribe/', {
            'email': 'dude@example.com',
            'newsletters': '',
        })
        self.assertEqual(resp.status_code, 400)
        data = json.loads(resp.content)
        self.assertEqual(data['status'], 'error')
        self.assertEqual(data['desc'], 'newsletters is missing')
        with self.assertRaises(models.Subscriber.DoesNotExist):
            models.Subscriber.objects.get(email='dude@example.com')

    def test_invalid_newsletters_error(self):
        """
        Should return an error and not create a subscriber if
        newsletters are invalid.
        """
        resp = self.client.post('/news/subscribe/', {
            'email': 'dude@example.com',
            'newsletters': 'mozilla-and-you,does-not-exist',
        })
        self.assertEqual(resp.status_code, 400)
        data = json.loads(resp.content)
        self.assertEqual(data['status'], 'error')
        self.assertEqual(data['desc'], 'invalid newsletter')
        with self.assertRaises(models.Subscriber.DoesNotExist):
            models.Subscriber.objects.get(email='dude@example.com')

    def test_invalid_language_error(self):
        """
        Should return an error and not create a subscriber if
        language invalid.
        """
        resp = self.client.post('/news/subscribe/', {
            'email': 'dude@example.com',
            'newsletters': 'mozilla-and-you',
            'lang': '55'
        })
        self.assertEqual(resp.status_code, 400)
        data = json.loads(resp.content)
        self.assertEqual(data['status'], 'error')
        self.assertEqual(data['desc'], 'invalid language')
        with self.assertRaises(models.Subscriber.DoesNotExist):
            models.Subscriber.objects.get(email='dude@example.com')

    @patch('news.views.get_user_data')
    @patch('news.views.update_user.delay')
    def test_blank_language_okay(self, uu_mock, get_user_data):
        """
        Should work if language is left blank.
        """
        get_user_data.return_value = None  # new user
        resp = self.client.post('/news/subscribe/', {
            'email': 'dude@example.com',
            'newsletters': 'mozilla-and-you',
            'lang': ''
        })
        self.assertEqual(resp.status_code, 200, resp.content)
        data = json.loads(resp.content)
        self.assertEqual(data['status'], 'ok')
        sub = models.Subscriber.objects.get(email='dude@example.com')
        uu_mock.assert_called_with(ANY, sub.email, sub.token,
                                   True, views.SUBSCRIBE, False)

    @patch('news.views.get_user_data')
    @patch('news.views.update_user.delay')
    def test_subscribe_success(self, uu_mock, get_user_data):
        """Subscription should work."""
        get_user_data.return_value = None  # new user
        resp = self.client.post('/news/subscribe/', {
            'email': 'dude@example.com',
            'newsletters': 'mozilla-and-you',
        })
        self.assertEqual(resp.status_code, 200, resp.content)
        data = json.loads(resp.content)
        self.assertEqual(data['status'], 'ok')
        sub = models.Subscriber.objects.get(email='dude@example.com')
        uu_mock.assert_called_with(ANY, sub.email, sub.token,
                                   True, views.SUBSCRIBE, False)

    @patch('news.views.get_user_data')
    def test_sync_requires_ssl(self, get_user_data):
        """sync=Y requires SSL"""
        get_user_data.return_value = None  # new user
        resp = self.client.post('/news/subscribe/', {
            'email': 'dude@example.com',
            'newsletters': 'mozilla-and-you',
            'lang': 'en',
            'sync': 'Y',
        })
        self.assertEqual(resp.status_code, 401, resp.content)
        data = json.loads(resp.content)
        self.assertEqual(errors.BASKET_SSL_REQUIRED, data['code'])

    @patch('news.views.get_user_data')
    def test_sync_case_insensitive(self, get_user_data):
        """sync=y also works (case-insensitive)"""
        get_user_data.return_value = None  # new user
        resp = self.client.post('/news/subscribe/', {
            'email': 'dude@example.com',
            'newsletters': 'mozilla-and-you',
            'lang': 'en',
            'sync': 'y',
        })
        self.assertEqual(resp.status_code, 401, resp.content)
        data = json.loads(resp.content)
        self.assertEqual(errors.BASKET_SSL_REQUIRED, data['code'])

    @patch('news.views.get_user_data')
    def test_sync_requires_api_key(self, get_user_data):
        """sync=Y requires API key"""
        get_user_data.return_value = None  # new user
        # Use SSL but no API key
        resp = self.ssl_post('/news/subscribe/', {
            'email': 'dude@example.com',
            'newsletters': 'mozilla-and-you',
            'lang': 'en',
            'sync': 'Y',
        })
        self.assertEqual(resp.status_code, 401, resp.content)
        data = json.loads(resp.content)
        self.assertEqual(errors.BASKET_AUTH_ERROR, data['code'])

    @patch('news.views.get_user_data')
    @patch('news.views.update_user.delay')
    def test_sync_with_ssl_and_api_key(self, uu_mock, get_user_data):
        """sync=Y with SSL and api key should work."""
        get_user_data.return_value = None  # new user
        auth = APIUser.objects.create(name="test")
        resp = self.ssl_post('/news/subscribe/', {
            'email': 'dude@example.com',
            'newsletters': 'mozilla-and-you',
            'sync': 'Y',
            'api-key': auth.api_key,
        })
        self.assertEqual(resp.status_code, 200, resp.content)
        data = json.loads(resp.content)
        self.assertEqual(data['status'], 'ok')
        sub = models.Subscriber.objects.get(email='dude@example.com')
        uu_mock.assert_called_with(ANY, sub.email, sub.token,
                                   True, views.SUBSCRIBE, False)

    @patch('news.views.get_user_data')
    @patch('news.views.update_user.delay')
    def test_optin_requires_ssl(self, uu_mock, get_user_data):
        """optin=Y requires SSL, optin = False otherwise"""
        get_user_data.return_value = None  # new user
        auth = APIUser.objects.create(name="test")
        resp = self.client.post('/news/subscribe/', {
            'email': 'dude@example.com',
            'newsletters': 'mozilla-and-you',
            'lang': 'en',
            'optin': 'Y',
            'api-key': auth.api_key,
        })
        sub = models.Subscriber.objects.get(email='dude@example.com')
        self.assertEqual(resp.status_code, 200, resp.content)
        uu_mock.assert_called_with(ANY, sub.email, sub.token,
                                   True, views.SUBSCRIBE, False)

    @patch('news.views.get_user_data')
    @patch('news.views.update_user.delay')
    def test_optin_requires_api_key(self, uu_mock, get_user_data):
        """optin=Y requires API key, optin = False otherwise"""
        get_user_data.return_value = None  # new user
        resp = self.ssl_post('/news/subscribe/', {
            'email': 'dude@example.com',
            'newsletters': 'mozilla-and-you',
            'lang': 'en',
            'optin': 'Y',
        })
        sub = models.Subscriber.objects.get(email='dude@example.com')
        self.assertEqual(resp.status_code, 200, resp.content)
        uu_mock.assert_called_with(ANY, sub.email, sub.token,
                                   True, views.SUBSCRIBE, False)

    @patch('news.views.get_user_data')
    @patch('news.views.update_user.delay')
    def test_optin_with_api_key_and_ssl(self, uu_mock, get_user_data):
        """optin=Y requires API key"""
        get_user_data.return_value = None  # new user
        auth = APIUser.objects.create(name="test")
        resp = self.ssl_post('/news/subscribe/', {
            'email': 'dude@example.com',
            'newsletters': 'mozilla-and-you',
            'lang': 'en',
            'optin': 'Y',
            'api-key': auth.api_key,
        })
        self.assertEqual(resp.status_code, 200, resp.content)
        data = json.loads(resp.content)
        self.assertEqual(data['status'], 'ok')
        sub = models.Subscriber.objects.get(email='dude@example.com')
        uu_mock.assert_called_with(ANY, sub.email, sub.token,
                                   True, views.SUBSCRIBE, True)

    @patch('news.views.get_user_data')
    @patch('news.views.update_user.delay')
    def test_optin_case_insensitive(self, uu_mock, get_user_data):
        """optin=y also works (case-insensitive)"""
        get_user_data.return_value = None  # new user
        auth = APIUser.objects.create(name="test")
        resp = self.ssl_post('/news/subscribe/', {
            'email': 'dude@example.com',
            'newsletters': 'mozilla-and-you',
            'lang': 'en',
            'optin': 'y',
            'api-key': auth.api_key,
        })
        self.assertEqual(resp.status_code, 200, resp.content)
        data = json.loads(resp.content)
        self.assertEqual(data['status'], 'ok')
        sub = models.Subscriber.objects.get(email='dude@example.com')
        uu_mock.assert_called_with(ANY, sub.email, sub.token,
                                   True, views.SUBSCRIBE, True)


class TestNewslettersAPI(TestCase):
    def setUp(self):
        self.url = reverse('newsletters_api')
        self.rf = RequestFactory()

    def test_newsletters_view(self):
        # We can fetch the newsletter data
        nl1 = models.Newsletter.objects.create(
            slug='slug',
            title='title',
            active=False,
            languages='en-US,fr',
            vendor_id='VENDOR1',
        )

        models.Newsletter.objects.create(slug='slug2', vendor_id='VENDOR2')

        req = self.rf.get(self.url)
        resp = views.newsletters(req)
        data = json.loads(resp.content)
        newsletters = data['newsletters']
        self.assertEqual(2, len(newsletters))
        # Find the 'slug' newsletter in the response
        obj = newsletters['slug']

        self.assertEqual(nl1.title, obj['title'])
        self.assertEqual(nl1.active, obj['active'])
        for lang in ['en-US', 'fr']:
            self.assertIn(lang, obj['languages'])

    def test_strip_languages(self):
        # If someone edits Newsletter and puts whitespace in the languages
        # field, we strip it on save
        nl1 = models.Newsletter.objects.create(
            slug='slug',
            title='title',
            active=False,
            languages='en-US, fr, de ',
            vendor_id='VENDOR1',
        )
        nl1 = models.Newsletter.objects.get(id=nl1.id)
        self.assertEqual('en-US,fr,de', nl1.languages)

    def test_newsletter_languages(self):
        # newsletter_languages() returns the set of languages
        # of the newsletters
        # (Note that newsletter_languages() is not part of the external
        # API, but is used internally)
        models.Newsletter.objects.create(
            slug='slug',
            title='title',
            active=False,
            languages='en-US',
            vendor_id='VENDOR1',
        )
        models.Newsletter.objects.create(
            slug='slug2',
            title='title',
            active=False,
            languages='fr, de ',
            vendor_id='VENDOR2',
        )
        models.Newsletter.objects.create(
            slug='slug3',
            title='title',
            active=False,
            languages='en-US, fr',
            vendor_id='VENDOR3',
        )
        expect = set(['en-US', 'fr', 'de'])
        self.assertEqual(expect, newsletter_languages())

    def test_newsletters_cached(self):
        models.Newsletter.objects.create(
            slug='slug',
            title='title',
            vendor_id='VEND1',
            active=False,
            languages='en-US, fr, de ',
        )
        # This should get the data cached
        newsletter_fields()
        # Now request it again and it shouldn't have to generate the
        # data from scratch.
        with patch('news.newsletters._get_newsletters_data') as get:
            newsletter_fields()
        self.assertFalse(get.called)

    def test_cache_clearing(self):
        # Our caching of newsletter data doesn't result in wrong answers
        # when newsletters change
        models.Newsletter.objects.create(
            slug='slug',
            title='title',
            vendor_id='VEND1',
            active=False,
            languages='en-US, fr, de ',
        )
        vendor_ids = newsletter_fields()
        self.assertEqual([u'VEND1'], vendor_ids)
        # Now add another newsletter
        models.Newsletter.objects.create(
            slug='slug2',
            title='title2',
            vendor_id='VEND2',
            active=False,
            languages='en-US, fr, de ',
        )
        vendor_ids2 = set(newsletter_fields())
        self.assertEqual(set([u'VEND1', u'VEND2']), vendor_ids2)

    def test_cache_clear_on_delete(self):
        # Our caching of newsletter data doesn't result in wrong answers
        # when newsletters are deleted
        nl1 = models.Newsletter.objects.create(
            slug='slug',
            title='title',
            vendor_id='VEND1',
            active=False,
            languages='en-US, fr, de ',
        )
        vendor_ids = newsletter_fields()
        self.assertEqual([u'VEND1'], vendor_ids)
        # Now delete it
        nl1.delete()
        vendor_ids = newsletter_fields()
        self.assertEqual([], vendor_ids)


class TestLanguageCodeIsValid(TestCase):
    def test_empty_string(self):
        """Empty string is accepted as a language code"""
        self.assertTrue(language_code_is_valid(''))

    def test_none(self):
        """None is a TypeError"""
        with self.assertRaises(TypeError):
            language_code_is_valid(None)

    def test_zero(self):
        """0 is a TypeError"""
        with self.assertRaises(TypeError):
            language_code_is_valid(0)

    def test_exact_2_letter(self):
        """2-letter code that's in the list is valid"""
        self.assertTrue(language_code_is_valid('az'))

    def test_exact_3_letter(self):
        """3-letter code is valid.

        There are a few of these."""
        self.assertTrue(language_code_is_valid('azq'))

    def test_exact_5_letter(self):
        """5-letter code that's in the list is valid"""
        self.assertTrue(language_code_is_valid('az-BY'))

    def test_case_insensitive(self):
        """Matching is not case sensitive"""
        self.assertTrue(language_code_is_valid('az-BY'))
        self.assertTrue(language_code_is_valid('aZ'))
        self.assertTrue(language_code_is_valid('QW'))

    def test_wrong_length(self):
        """A code that's not a valid length is not valid."""
        self.assertFalse(language_code_is_valid('az-'))
        self.assertFalse(language_code_is_valid('a'))
        self.assertFalse(language_code_is_valid('azqr'))
        self.assertFalse(language_code_is_valid('az-BY2'))

    def test_wrong_format(self):
        """A code that's not a valid format is not valid."""
        self.assertFalse(language_code_is_valid('a2'))
        self.assertFalse(language_code_is_valid('asdfj'))
        self.assertFalse(language_code_is_valid('az_BY'))


class RecoveryViewTest(TestCase):
    # See the task tests for more
    def setUp(self):
        self.url = reverse('send_recovery_message')

    def test_no_email(self):
        """email not provided - return 400"""
        resp = self.client.post(self.url, {})
        self.assertEqual(400, resp.status_code)

    def test_bad_email(self):
        """Invalid email should return 400"""
        resp = self.client.post(self.url, {'email': 'not_an_email'})
        self.assertEqual(400, resp.status_code)

    @patch('news.views.validate_email', none_mock)
    @patch('news.views.get_user_data', autospec=True)
    def test_unknown_email(self, mock_get_user_data):
        """Unknown email should return 404"""
        email = 'dude@example.com'
        mock_get_user_data.return_value = None
        resp = self.client.post(self.url, {'email': email})
        self.assertEqual(404, resp.status_code)

    @patch('news.views.validate_email', none_mock)
    @patch('news.views.get_user_data', autospec=True)
    @patch('news.views.send_recovery_message_task.delay', autospec=True)
    def test_known_email(self, mock_send_recovery_message_task,
                         mock_get_user_data):
        """email provided - pass to the task, return 200"""
        email = 'dude@example.com'
        mock_get_user_data.return_value = {'dummy': 2}
        # It should pass the email to the task
        resp = self.client.post(self.url, {'email': email})
        self.assertEqual(200, resp.status_code)
        mock_send_recovery_message_task.assert_called_with(email)


@patch('news.views.get_valid_email')
class TestValidateEmail(TestCase):
    email = 'dude@example.com'
    data = {'email': email}

    def test_valid_email(self, mock_valid):
        """Should return without raising an exception for a valid email."""
        mock_valid.return_value = (self.email, False)
        views.validate_email(self.data)
        mock_valid.assert_called_with(self.email)

    def test_invalid_email(self, mock_valid):
        """Should raise an exception for an invalid email."""
        mock_valid.return_value = (None, False)
        with self.assertRaises(views.EmailValidationError) as cm:
            views.validate_email(self.data)
        mock_valid.assert_called_with(self.email)
        self.assertIsNone(cm.exception.suggestion)

    def test_invalid_email_suggestion(self, mock_valid):
        """Should raise an exception for a misspelled email and offer a suggestion."""
        mock_valid.return_value = ('walter@example.com', True)
        with self.assertRaises(views.EmailValidationError) as cm:
            views.validate_email(self.data)
        mock_valid.assert_called_with(self.email)
        self.assertEqual(cm.exception.suggestion, mock_valid.return_value[0])

    def test_already_validated(self, mock_valid):
        """Should not call validation stuff if validated parameter set."""
        views.validate_email({'validated': 'true'})
        self.assertFalse(mock_valid.called)
