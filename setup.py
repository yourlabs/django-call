import os

from setuptools import setup, find_packages


def read(fname):
    return open(os.path.join(os.path.dirname(__file__), fname)).read()

setup(
    name='django-call',
    version='0.0.9',
    description='Leverage uWSGI spooler and cron in Django',
    author='James Pic',
    author_email='jpic@yourlabs.org',
    url='https://github.com/yourlabs/django-call',
    packages=find_packages('.'),
    include_package_data=True,
    long_description=read('README.rst'),
    keywords='django uwsgi cache spooler',
    install_requires=[
        'django-picklefield',
    ],
    extras_require=dict(
        django=[
            'django-threadlocals',
            'django-ipware',
        ],
        example=[
            'django>=2.0',
            'crudlfap',
        ],
    ),
    entry_points={
        'console_scripts': [
            'djcall-example = djcall_example.manage:main',
        ],
    },
    classifiers=[
        'Development Status :: 2 - Pre-Alpha',
        'Environment :: Web Environment',
        'Framework :: Django',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
        'Programming Language :: Python :: 3',
        'Topic :: Internet :: WWW/HTTP',
        'Topic :: Software Development :: Libraries :: Python Modules',
    ]
)
