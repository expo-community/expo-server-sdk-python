from setuptools import find_packages
from setuptools import setup
import os
import re


HERE = os.path.abspath(os.path.dirname(__file__))


README_PATH = os.path.join(HERE, 'README.md')
try:
    with open(README_PATH) as fd:
        README = fd.read()
except IOError:
    README = ''


setup(
    name='exponent_server_sdk',
    version=__import__('exponent_server_sdk').__version__,
    description='Exponent Server SDK for Python',
    long_description=README,
    url='https://github.com/exponent/exponent-server-sdk-python',
    author='Exponent Team',
    author_email='exponent.team@gmail.com',
    license='MIT',
    install_requires=[
        'requests',
    ],
    packages=find_packages(),
    zip_safe=False
)
