from django.contrib.auth.base_user import BaseUserManager
from django.contrib.auth.models import AbstractUser
from django.db import models

# Create your models here.
"""
1 .The CustomUser model defines how the user table should look.
AbstractUser / AbstractBaseUser provide Django’s default user behavior.
Migrations turn this definition into the real database table.
Changing the model alone is not enough, because authentication also depends on how users are created.

2 .BaseUserManager customizes how users are created.
   In create_user, Django:

      normalizes the email

      creates a user object in RAM using self.model                                                                                                                                                                                                                                                     

      does not pass the password yet because passwords must be hashed and hashing requires a user instance

      hashes the password using set_password

      saves the user to the database

3 .save() is the only step that actually writes to the database.

4 .create_superuser is a function, not a class, because a superuser is not a different type of user.
It only adds permission flags and then reuses create_user.

5 .When createsuperuser is run in the terminal, Django’s management command collects the email and password first, then calls create_superuser(email, password) with those values.
"""


class CustomUserManager(BaseUserManager):               #used mostly by the developers(terminal) or non-website parts(like terminal) or no form needed part(but this is not highly recommended to remember) this is to create a user in the DB  ,remember save() always save things to the DB ,so if you see save() realize it is going to DB
    def create_user(self,email,password,**extra_fields):
        if not email:
            raise ValueError("Please Enter a Proper Email")

        email=self.normalize_email(email)
        user = self.model(email=email,**extra_fields)
        user.set_password(password)
        user.save()
        return user

    def create_superuser(self,email,password,**extra_fields):
        extra_fields.setdefault('is_staff',True)
        extra_fields.setdefault('is_superuser',True)
        extra_fields.setdefault('is_active',True)

        return self.create_user(email,password,**extra_fields)


class CustomUser(AbstractUser):
    email = models.EmailField(unique=True)
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['username']          #this line is only for superuser

    objects = CustomUserManager()





