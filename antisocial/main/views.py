from annoying.decorators import render_to
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404
import zipfile
import opml
from django.utils.simplejson import dumps, loads

from antisocial.main.models import Feed, Subscription, UEntry
import antisocial.main.tasks as tasks


@render_to('main/index.html')
def index(request):
    unread_count = 0
    if not request.user.is_anonymous():
        unread_count = UEntry.objects.filter(
            user=request.user,
            read=False).count()
    return dict(unread_count=unread_count)


@login_required
def entries(request):
    unread_entries = UEntry.objects.select_related().filter(
        user=request.user,
        read=False,
    ).order_by("entry__published")
    return HttpResponse(
        dumps([ue.as_dict() for ue in unread_entries]),
        mimetype="application/json"
    )


@login_required
def entry_api(request, id):
    unread_count = UEntry.objects.filter(
        user=request.user,
        read=False,
    ).count()
    ue = get_object_or_404(UEntry, id=id)
    if request.method == "PUT":
        d = loads(request.read())
        ue.read = d['read']
        ue.save()
    d = ue.as_dict()
    d['unread_count'] = unread_count
    return HttpResponse(
        dumps(d),
        mimetype="application/json"
    )


@login_required
@render_to('main/subscriptions.html')
def subscriptions(request):
    subscriptions = Subscription.objects.select_related().filter(
        user=request.user).order_by("feed__next_fetch")
    return dict(subscriptions=subscriptions)


@login_required
@render_to('main/subscription.html')
def subscription(request, id):
    feed = get_object_or_404(Feed, id=id)
    subs = []
    r = feed.subscription_set.filter(user=request.user)
    if r.count() > 0:
        subs = r[0]
    return dict(feed=feed, subscription=subs)


@login_required
def subscription_mark_read(request, id):
    feed = get_object_or_404(Feed, id=id)
    subs = feed.subscription_set.filter(user=request.user)[0]
    for ue in subs.unread_entries():
        ue.read = True
        ue.save()
    return HttpResponseRedirect(subs.feed.get_absolute_url())


@login_required
def subscription_fetch(request, id):
    """ fetch it now, ignoring the schedule
    mainly for debugging. """
    feed = get_object_or_404(Feed, id=id)
    tasks.process_feed.delay(feed.id)
    return HttpResponseRedirect(feed.get_absolute_url())


@login_required
def unsubscribe(request, id):
    feed = get_object_or_404(Feed, id=id)
    subs = feed.subscription_set.filter(user=request.user)[0]
    for ue in subs.unread_entries():
        ue.read = True
        ue.save()
    subs.delete()
    if feed.subscription_set.count() == 0:
        feed.delete()
    return HttpResponseRedirect("/subscriptions/")


@login_required
def subscribe(request, id):
    feed = get_object_or_404(Feed, id=id)
    feed.subscribe_user(request.user)
    return HttpResponseRedirect("/subscriptions/")


@login_required
@render_to("main/import_feeds.html")
def import_feeds(request):
    if request.method != "POST":
        return HttpResponseRedirect("/subscriptions/")
    cnt = 0

    feed_urls = []
    try:
        with zipfile.ZipFile(
                request.FILES['zip'],
                "r",
                zipfile.ZIP_STORED) as openzip:
            filelist = openzip.infolist()
            for f in filelist:
                if f.filename.startswith("__"):
                    continue
                if f.filename.startswith("."):
                    continue
                if f.filename.endswith("subscriptions.xml"):
                    opmlfile = openzip.read(f)
                    outline = opml.from_string(opmlfile)
                    for o in outline:
                        for o2 in o:
                            feed_urls.append(getattr(o2, 'xmlUrl'))
                            cnt += 1
    except Exception, e:
        return HttpResponse("error parsing file: %s" % str(e))

    for url in feed_urls:
        tasks.add_feed.delay(url, user=request.user)
    return dict(
        total=cnt
    )


@login_required
def add_subscription(request):
    if request.method != "POST":
        return HttpResponseRedirect("/subscriptions/")
    url = request.POST.get('url', False)
    if not url:
        return HttpResponseRedirect("/subscriptions/")
    r = Feed.objects.filter(url=url)
    if r.count() > 0:
        r[0].subscribe_user(request.user)
        return HttpResponseRedirect("/subscriptions/")
    tasks.add_feed.delay(url, user=request.user)
    return HttpResponseRedirect("/subscriptions/")
