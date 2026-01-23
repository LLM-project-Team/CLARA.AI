from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.utils import timezone
from .models import Circular
from users.models import UserProfile
import json


# Template definitions for quick generation
CIRCULAR_TEMPLATES = {
    'holiday': {
        'title': 'Holiday Declaration',
        'icon': 'fa-umbrella-beach',
        'description': 'Draft a notice for a holiday or festival.',
        'template': """OFFICIAL CIRCULAR
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Circular No: {circular_no}
Date: {date}

Subject: Holiday Declaration - {occasion}

Dear Staff and Students,

This is to inform all concerned that the institution will remain closed on {holiday_date} on the occasion of {occasion}.

All regular classes and office activities will resume on the following working day.

Students are advised to utilize this time for self-study and preparation.

For any urgent matters, please contact the college office.


{signature}
{designation}
{institution}"""
    },
    'exam': {
        'title': 'Exam Schedule',
        'icon': 'fa-clock',
        'description': 'Notify about upcoming examination dates.',
        'template': """OFFICIAL CIRCULAR
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Circular No: {circular_no}
Date: {date}

Subject: {exam_type} Examination Schedule

Dear Students,

This is to inform all students that the {exam_type} examinations for the academic year {academic_year} will be conducted as per the following schedule:

Examination Period: {start_date} to {end_date}

Important Instructions:
1. Students must carry their ID cards to the examination hall.
2. Report to the examination hall 15 minutes before the scheduled time.
3. Electronic devices are strictly prohibited inside the examination hall.
4. Any form of malpractice will result in strict disciplinary action.

The detailed timetable will be displayed on the notice board and college website.

All the best for your examinations!


{signature}
{designation}
{institution}"""
    },
    'meeting': {
        'title': 'Staff Meeting',
        'icon': 'fa-users',
        'description': 'Call for a meeting with staff or department heads.',
        'template': """OFFICIAL CIRCULAR
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Circular No: {circular_no}
Date: {date}

Subject: {meeting_type} Meeting Notice

Dear {recipients},

A {meeting_type} meeting has been scheduled as per the following details:

Date: {meeting_date}
Time: {meeting_time}
Venue: {venue}

Agenda:
{agenda}

All concerned are requested to attend the meeting punctually. Please come prepared with relevant documents and reports.

Kindly confirm your attendance by replying to this circular.


{signature}
{designation}
{institution}"""
    },
    'disciplinary': {
        'title': 'Disciplinary Action',
        'icon': 'fa-triangle-exclamation',
        'description': 'Draft a formal warning or disciplinary notice.',
        'template': """OFFICIAL CIRCULAR
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Circular No: {circular_no}
Date: {date}

Subject: Disciplinary Notice

To All Students/Staff,

This circular is issued to bring to the notice of all concerned regarding the importance of maintaining discipline and decorum within the institution premises.

It has been observed that certain individuals have been found violating the institution's code of conduct. Such behavior is strictly unacceptable and will not be tolerated.

All students and staff are hereby warned that:

1. Any violation of institution rules will result in strict disciplinary action.
2. Repeated offenses may lead to suspension or expulsion.
3. The institution reserves the right to take legal action if necessary.

We expect full cooperation from everyone in maintaining a healthy and productive academic environment.


{signature}
{designation}
{institution}"""
    },
    'general': {
        'title': 'General Announcement',
        'icon': 'fa-bullhorn',
        'description': 'Create a general announcement for any purpose.',
        'template': """OFFICIAL CIRCULAR
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Circular No: {circular_no}
Date: {date}

Subject: {subject}

Dear {recipients},

{content}


{signature}
{designation}
{institution}"""
    },
    'event': {
        'title': 'Event Announcement',
        'icon': 'fa-calendar-star',
        'description': 'Announce an upcoming event or function.',
        'template': """OFFICIAL CIRCULAR
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Circular No: {circular_no}
Date: {date}

Subject: {event_name} - Event Announcement

Dear Staff and Students,

We are pleased to announce that {event_name} will be organized by the institution as per the following details:

Event: {event_name}
Date: {event_date}
Time: {event_time}
Venue: {venue}

{event_description}

All are cordially invited to participate and make this event a grand success.

For registration and queries, please contact {contact}.


{signature}
{designation}
{institution}"""
    }
}


def get_next_circular_number():
    """Generate next circular number for the year"""
    current_year = timezone.now().year
    last_circular = Circular.objects.filter(
        created_at__year=current_year
    ).order_by('-created_at').first()
    
    if last_circular:
        # Try to extract number from title or just increment count
        count = Circular.objects.filter(created_at__year=current_year).count() + 1
    else:
        count = 1
    
    return f"CIR/{current_year}/{count:03d}"


@login_required
def generator_view(request):
    """Main circular generator view - unified interface"""
    user_profile = UserProfile.get_by_email(request.user.email)
    
    # Check permissions
    if not user_profile or not user_profile.can_generate_circular():
        return render(request, 'circulars/access_denied.html', {
            'user_profile': user_profile,
            'user_name': user_profile.name if user_profile else request.user.username,
            'user_role': user_profile.role if user_profile else 'Unknown',
        })
    
    # Get history
    history = Circular.objects.filter(user=request.user).order_by('-created_at')[:10]
    
    context = {
        'history': history,
        'templates': CIRCULAR_TEMPLATES,
        'generated_content': None,
        'generated_title': None,
        'edit_mode': False,
        'user_profile': user_profile,
        'user_name': user_profile.name if user_profile else request.user.username,
        'user_role': user_profile.role if user_profile else 'Unknown',
    }
    
    # Handle template selection or custom prompt
    template_type = request.GET.get('template')
    auto_holiday = request.GET.get('auto_holiday')
    
    if template_type and template_type in CIRCULAR_TEMPLATES:
        template = CIRCULAR_TEMPLATES[template_type]
        # Generate with default placeholders
        content = template['template'].format(
            circular_no=get_next_circular_number(),
            date=timezone.now().strftime("%d %B %Y"),
            occasion="[Enter Occasion]",
            holiday_date="[Enter Date]",
            exam_type="[Semester/Internal/Model]",
            academic_year=f"{timezone.now().year}-{timezone.now().year + 1}",
            start_date="[Start Date]",
            end_date="[End Date]",
            meeting_type="[Staff/Department/Emergency]",
            recipients="All Concerned",
            meeting_date="[Meeting Date]",
            meeting_time="[Meeting Time]",
            venue="[Venue]",
            agenda="1. [Agenda Item 1]\n2. [Agenda Item 2]\n3. [Agenda Item 3]",
            subject="[Enter Subject]",
            content="[Enter your announcement content here]",
            event_name="[Event Name]",
            event_date="[Event Date]",
            event_time="[Event Time]",
            event_description="[Event Description]",
            contact="[Contact Person/Department]",
            signature=user_profile.name if user_profile else "Principal",
            designation=user_profile.role if user_profile else "Principal",
            institution="Institution Name"
        )
        context['generated_content'] = content
        context['generated_title'] = template['title']
        context['edit_mode'] = True
        context['template_type'] = template_type
    
    elif auto_holiday:
        # Quick holiday generation from dashboard
        template = CIRCULAR_TEMPLATES['holiday']
        content = template['template'].format(
            circular_no=get_next_circular_number(),
            date=timezone.now().strftime("%d %B %Y"),
            occasion=auto_holiday,
            holiday_date="[Enter Date]",
            signature=user_profile.name if user_profile else "Principal",
            designation=user_profile.role if user_profile else "Principal",
            institution="Institution Name"
        )
        context['generated_content'] = content
        context['generated_title'] = f"Holiday Declaration - {auto_holiday}"
        context['edit_mode'] = True
        context['template_type'] = 'holiday'
    
    return render(request, 'circulars/generator.html', context)


@login_required
def save_circular(request):
    """Save/Approve circular"""
    if request.method != 'POST':
        return redirect('circular_gen')
    
    user_profile = UserProfile.get_by_email(request.user.email)
    if not user_profile or not user_profile.can_generate_circular():
        messages.error(request, "You don't have permission to save circulars.")
        return redirect('circular_gen')
    
    title = request.POST.get('title', 'Untitled Circular')
    content = request.POST.get('content', '')
    category = request.POST.get('category', 'manual')
    
    if not content.strip():
        messages.error(request, "Circular content cannot be empty.")
        return redirect('circular_gen')
    
    # Save circular
    circular = Circular.objects.create(
        user=request.user,
        title=title,
        content=content,
        category=category
    )
    
    messages.success(request, f"Circular '{title}' has been saved successfully!")
    return redirect('circular_gen')


@login_required
def view_circular(request, circular_id):
    """View a saved circular"""
    user_profile = UserProfile.get_by_email(request.user.email)
    
    try:
        circular = Circular.objects.get(id=circular_id, user=request.user)
    except Circular.DoesNotExist:
        messages.error(request, "Circular not found.")
        return redirect('circular_gen')
    
    history = Circular.objects.filter(user=request.user).order_by('-created_at')[:10]
    
    context = {
        'history': history,
        'templates': CIRCULAR_TEMPLATES,
        'generated_content': circular.content,
        'generated_title': circular.title,
        'circular': circular,
        'view_mode': True,
        'user_profile': user_profile,
        'user_name': user_profile.name if user_profile else request.user.username,
        'user_role': user_profile.role if user_profile else 'Unknown',
    }
    
    return render(request, 'circulars/generator.html', context)


@login_required  
def delete_circular(request, circular_id):
    """Delete a circular"""
    if request.method != 'POST':
        return redirect('circular_gen')
    
    try:
        circular = Circular.objects.get(id=circular_id, user=request.user)
        circular.delete()
        messages.success(request, "Circular deleted successfully.")
    except Circular.DoesNotExist:
        messages.error(request, "Circular not found.")
    
    return redirect('circular_gen')


@login_required
def generate_ai_content(request):
    """AJAX endpoint for AI content generation (placeholder for future AI integration)"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Invalid request'}, status=400)
    
    user_profile = UserProfile.get_by_email(request.user.email)
    if not user_profile or not user_profile.can_generate_circular():
        return JsonResponse({'error': 'Permission denied'}, status=403)
    
    try:
        data = json.loads(request.body)
        prompt = data.get('prompt', '')
    except json.JSONDecodeError:
        prompt = request.POST.get('prompt', '')
    
    if not prompt:
        return JsonResponse({'error': 'Prompt is required'}, status=400)
    
    # TODO: Integrate with actual AI service (OpenAI, Gemini, etc.)
    # For now, return a template-based response
    
    generated_content = f"""OFFICIAL CIRCULAR
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Circular No: {get_next_circular_number()}
Date: {timezone.now().strftime("%d %B %Y")}

Subject: {prompt[:50]}...

Dear All,

[AI-generated content based on your prompt will appear here]

Your prompt was: "{prompt}"

This is a placeholder response. In production, this will be replaced with actual AI-generated content using services like OpenAI GPT or Google Gemini.


{user_profile.name if user_profile else 'Principal'}
{user_profile.role if user_profile else 'Principal'}"""
    
    return JsonResponse({
        'success': True,
        'content': generated_content,
        'title': f"Circular: {prompt[:30]}..."
    })