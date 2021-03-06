"""
.. module: lemur.authorities.service
    :platform: Unix
    :synopsis: This module contains all of the services level functions used to
    administer authorities in Lemur
    :copyright: (c) 2015 by Netflix Inc., see AUTHORS for more
    :license: Apache, see LICENSE for more details.
.. moduleauthor:: Kevin Glisson <kglisson@netflix.com>

"""
from flask import g
from flask import current_app

from lemur import database
from lemur.authorities.models import Authority
from lemur.roles import service as role_service
from lemur.notifications import service as notification_service

from lemur.roles.models import Role
from lemur.certificates.models import Certificate

from lemur.plugins.base import plugins


def update(authority_id, description=None, owner=None, active=None, roles=None):
    """
    Update a an authority with new values.

    :param authority_id:
    :param roles: roles that are allowed to use this authority
    :rtype : Authority
    :return:
    """
    authority = get(authority_id)
    if roles:
        authority = database.update_list(authority, 'roles', Role, roles)

    if active:
        authority.active = active

    authority.description = description
    authority.owner = owner
    return database.update(authority)


def create(kwargs):
    """
    Create a new authority.

    :rtype : Authority
    :return:
    """

    issuer = plugins.get(kwargs.get('pluginName'))

    kwargs['creator'] = g.current_user.email
    cert_body, intermediate, issuer_roles = issuer.create_authority(kwargs)

    cert = Certificate(cert_body, chain=intermediate)
    cert.owner = kwargs['ownerEmail']
    cert.description = "This is the ROOT certificate for the {0} certificate authority".format(kwargs.get('caName'))
    cert.user = g.current_user

    cert.notifications = notification_service.create_default_expiration_notifications(
        'DEFAULT_SECURITY',
        current_app.config.get('LEMUR_SECURITY_TEAM_EMAIL')
    )

    # we create and attach any roles that the issuer gives us
    role_objs = []
    for r in issuer_roles:

        role = role_service.create(
            r['name'],
            password=r['password'],
            description="{0} auto generated role".format(kwargs.get('pluginName')),
            username=r['username'])

        # the user creating the authority should be able to administer it
        if role.username == 'admin':
            g.current_user.roles.append(role)

        role_objs.append(role)

    authority = Authority(
        kwargs.get('caName'),
        kwargs['ownerEmail'],
        kwargs['pluginName'],
        cert_body,
        description=kwargs['caDescription'],
        chain=intermediate,
        roles=role_objs
    )

    database.update(cert)
    authority = database.create(authority)

    g.current_user.authorities.append(authority)

    return authority


def get_all():
    """
    Get all authorities that are currently in Lemur.

    :rtype : List
    :return:
    """
    query = database.session_query(Authority)
    return database.find_all(query, Authority, {}).all()


def get(authority_id):
    """
    Retrieves an authority given it's ID

    :rtype : Authority
    :param authority_id:
    :return:
    """
    return database.get(Authority, authority_id)


def get_by_name(authority_name):
    """
    Retrieves an authority given it's name.

    :param authority_name:
    :rtype : Authority
    :return:
    """
    return database.get(Authority, authority_name, field='name')


def get_authority_role(ca_name):
    """
    Attempts to get the authority role for a given ca uses current_user
    as a basis for accomplishing that.

    :param ca_name:
    """
    if g.current_user.is_admin:
        authority = get_by_name(ca_name)
        # TODO we should pick admin ca roles for admin
        return authority.roles[0]
    else:
        for role in g.current_user.roles:
            if role.authority:
                if role.authority.name == ca_name:
                    return role


def render(args):
    """
    Helper that helps us render the REST Api responses.
    :param args:
    :return:
    """
    query = database.session_query(Authority)
    sort_by = args.pop('sort_by')
    sort_dir = args.pop('sort_dir')
    page = args.pop('page')
    count = args.pop('count')
    filt = args.pop('filter')

    if filt:
        terms = filt.split(';')
        if 'active' in filt:  # this is really weird but strcmp seems to not work here??
            query = query.filter(Authority.active == terms[1])
        else:
            query = database.filter(query, Authority, terms)

    # we make sure that a user can only use an authority they either own are are a member of - admins can see all
    if not g.current_user.is_admin:
        authority_ids = []
        for role in g.current_user.roles:
            if role.authority:
                authority_ids.append(role.authority.id)
        query = query.filter(Authority.id.in_(authority_ids))

    query = database.find_all(query, Authority, args)

    if sort_by and sort_dir:
        query = database.sort(query, Authority, sort_by, sort_dir)

    return database.paginate(query, page, count)
