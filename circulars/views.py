from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.utils import timezone
from .models import Circular, CircularTemplate
from users.models import UserProfile
from utils.festival_dates import resolve_festival_date
from aa.llm_client import call_llm_chat, LLMError, LIGHT_MODEL
import json
import os
import requests
import logging

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────
# Institution constants  (match the real SIET letterhead)
# ─────────────────────────────────────────────────────────────────
INSTITUTION_HEADER = """\
               SRI SHAKTHI INSTITUTE OF ENGINEERING AND TECHNOLOGY
               Coimbatore - 641 062, L&T By Pass, Tamil Nadu, India"""

COPY_TO_BLOCK = """\
Copy to:
    \u2022  The Chairman Sir for kind favor of Information
    \u2022  The Secretary Sir and Joint Secretary Sir for kind favor of Information
    \u2022  Deans, Directors and All HoDs for needful actions
    \u2022  Hostel Wardens
    \u2022  Office File"""

def _academic_year():
    """Return academic year string e.g. '2024-2025'"""
    now = timezone.now()
    yr = now.year
    # Academic year starts in July; before July it's the previous year
    if now.month < 7:
        return f"{yr - 1}-{yr}"
    return f"{yr}-{yr + 1}"

# ─────────────────────────────────────────────────────────────────
# Quick-generation template definitions  (SIET letterhead format)
# ─────────────────────────────────────────────────────────────────
CIRCULAR_TEMPLATES = {
    'holiday': {
        'title': 'Holiday Declaration',
        'icon': 'fa-umbrella-beach',
        'description': 'Draft a notice for a holiday or festival.',
        'template': """Ref : {circular_no}                                         {date}

                                    CIRCULAR

Subject: Holiday Declaration - {occasion}

We are pleased to inform you that our Institute will observe a holiday on {holiday_date} on the occasion of {occasion}. Please note that the Mess will be closed during this holiday period.

Regular Classes and activities will resume on the next working day.

We wish you all a happy and prosperous {occasion}. May this festive season bring light, happiness, and success in all your endeavors.

{copy_to}"""
    },
    'exam': {
        'title': 'Exam Schedule',
        'icon': 'fa-clock',
        'description': 'Notify about upcoming examination dates.',
        'template': """Ref : {circular_no}                                         {date}

                                    CIRCULAR

Subject: Examination Schedule - {academic_year}

This is to inform all students that the {exam_type} Examinations for the Academic Year {academic_year} will be held from {start_date} to {end_date}.

Students are instructed to:
1. Carry their Identity Cards and Hall Tickets to the examination hall.
2. Report to the examination hall 15 minutes before the scheduled time.
3. Electronic devices are strictly prohibited inside the examination hall.
4. Any form of malpractice will result in strict disciplinary action as per the Institute's rules.

The detailed timetable has been displayed on the Department Notice Boards and the Institute website.

All students are wished the very best for their examinations.

{copy_to}"""
    },
    'meeting': {
        'title': 'Staff Meeting',
        'icon': 'fa-users',
        'description': 'Call for a meeting with staff or department heads.',
        'template': """Ref : {circular_no}                                         {date}

                                    CIRCULAR

Subject: {meeting_type} Meeting

All {recipients} are hereby informed that a {meeting_type} Meeting is scheduled as follows:

    Date    : {meeting_date}
    Time    : {meeting_time}
    Venue   : {venue}

Agenda:
{agenda}

All concerned are requested to attend the meeting punctually and come prepared with relevant documents and progress reports.

{copy_to}"""
    },
    'disciplinary': {
        'title': 'Disciplinary Notice',
        'icon': 'fa-triangle-exclamation',
        'description': 'Draft a formal warning or disciplinary notice.',
        'template': """Ref : {circular_no}                                         {date}

                                    CIRCULAR

Subject: Disciplinary Notice

This circular is issued to bring to the notice of all students and staff the importance of maintaining discipline and decorum within the Institute premises.

It has been observed that certain individuals have not been adhering to the Institute's Code of Conduct. Such behavior is strictly unacceptable.

All students and staff are hereby warned that:
1. Any violation of Institute rules will result in strict disciplinary action.
2. Repeated offences may lead to suspension or expulsion from the Institute.
3. The Institute reserves the right to take further action as deemed necessary.

Full cooperation from all is expected in maintaining a healthy and productive academic environment.

{copy_to}"""
    },
    'general': {
        'title': 'General Announcement',
        'icon': 'fa-bullhorn',
        'description': 'Create a general announcement for any purpose.',
        'template': """Ref : {circular_no}                                         {date}

                                    CIRCULAR

Subject: General Announcement

{content}

{copy_to}"""
    },
    'event': {
        'title': 'Event Announcement',
        'icon': 'fa-calendar-star',
        'description': 'Announce an upcoming event or function.',
        'template': """Ref : {circular_no}                                         {date}

                                    CIRCULAR

Subject: {event_name} - Event Announcement

We are pleased to inform all students and faculty members that {event_name} will be organised by the Institute as per the details given below:

    Event   : {event_name}
    Date    : {event_date}
    Time    : {event_time}
    Venue   : {venue}

{event_description}

For registration and further details, please contact {contact}.

All are cordially invited to participate and make this event a grand success.

{copy_to}"""
    }
}


def _resolve_festival_date(occasion):
    """
    Thin wrapper around the shared lookup in utils.festival_dates.
    Falls back to '[Enter Date]' if the festival isn't found.
    """
    return resolve_festival_date(occasion, timezone.now().year)


def get_next_circular_number():
    """Generate next circular number using real SIET format: SIET/AD/YYYY-YYYY/NN"""
    acad = _academic_year()
    count = Circular.objects.count() + 1
    return f"SIET/AD/{acad}/{count:02d}"


@login_required
def upload_template(request):
    """Upload or replace the circular letterhead template"""
    user_profile = UserProfile.get_by_email(request.user.email)
    
    if not user_profile or not user_profile.can_generate_circular():
        return render(request, 'circulars/access_denied.html', {
            'user_profile': user_profile,
            'user_name': user_profile.name if user_profile else request.user.username,
            'user_role': user_profile.role if user_profile else 'Unknown',
        })
    
    active_template = CircularTemplate.get_active_template(request.user)
    
    if request.method == 'POST':
        template_image = request.FILES.get('template_image')
        template_name = request.POST.get('name', 'Default Template').strip() or 'Default Template'
        content_top = request.POST.get('content_top_margin', 72)
        content_bottom = request.POST.get('content_bottom_margin', 45)
        
        if not template_image:
            messages.error(request, 'Please select a template image to upload.')
            return redirect('circular_upload_template')
        
        # Validate file type
        allowed_types = ['image/png', 'image/jpeg', 'image/jpg']
        if template_image.content_type not in allowed_types:
            messages.error(request, 'Only PNG and JPG images are allowed.')
            return redirect('circular_upload_template')
        
        # Validate file size (max 5MB)
        if template_image.size > 5 * 1024 * 1024:
            messages.error(request, 'Template image must be less than 5MB.')
            return redirect('circular_upload_template')
        
        try:
            content_top = int(content_top)
            content_bottom = int(content_bottom)
        except (ValueError, TypeError):
            content_top = 58
            content_bottom = 45
        
        # Deactivate existing templates and create new one
        CircularTemplate.objects.filter(user=request.user).update(is_active=False)
        
        CircularTemplate.objects.create(
            user=request.user,
            name=template_name,
            template_image=template_image,
            is_active=True,
            content_top_margin=content_top,
            content_bottom_margin=content_bottom,
        )
        
        messages.success(request, f'Template "{template_name}" uploaded successfully! You can now generate circulars.')
        return redirect('circular_gen')
    
    context = {
        'active_template': active_template,
        'user_profile': user_profile,
        'user_name': user_profile.name if user_profile else request.user.username,
        'user_role': user_profile.role if user_profile else 'Unknown',
        'active_page': 'circulars',
    }
    return render(request, 'circulars/upload_template.html', context)


@login_required
def delete_template(request):
    """Delete the active circular template"""
    if request.method != 'POST':
        return redirect('circular_upload_template')
    
    CircularTemplate.objects.filter(user=request.user, is_active=True).update(is_active=False)
    messages.success(request, 'Template removed. Please upload a new template to generate circulars.')
    return redirect('circular_upload_template')


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
    
    # Check if user has an active template - redirect to upload if not
    active_template = CircularTemplate.get_active_template(request.user)
    if not active_template:
        messages.warning(request, 'Please upload a circular template before generating circulars. '
                        'The template should include your college logo, header, and signature.')
        return redirect('circular_upload_template')
    
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
        'active_page': 'circulars',
        'active_template': active_template,
    }
    
    # Handle template selection or custom prompt
    template_type = request.GET.get('template')
    auto_holiday = request.GET.get('auto_holiday')
    
    if template_type and template_type in CIRCULAR_TEMPLATES:
        template = CIRCULAR_TEMPLATES[template_type]
        # For holiday templates, resolve the date via AI
        if template_type == 'holiday':
            occasion = request.GET.get('occasion', '[Enter Occasion]')
            holiday_date = _resolve_festival_date(occasion) if occasion != '[Enter Occasion]' else '[Enter Date]'
        else:
            occasion = '[Enter Occasion]'
            holiday_date = '[Enter Date]'
        content = _generate_body_content(template['template'], template_type,
                                          occasion=occasion, holiday_date=holiday_date)
        context['generated_content'] = content
        context['generated_title'] = template['title']
        context['edit_mode'] = True
        context['template_type'] = template_type
    
    elif auto_holiday:
        # Quick holiday generation from dashboard — resolve the actual date via AI
        template = CIRCULAR_TEMPLATES['holiday']
        holiday_date = _resolve_festival_date(auto_holiday)
        content = _generate_body_content(template['template'], 'holiday',
                                          occasion=auto_holiday, holiday_date=holiday_date)
        context['generated_content'] = content
        context['generated_title'] = f"Holiday Declaration - {auto_holiday}"
        context['edit_mode'] = True
        context['template_type'] = 'holiday'
    
    return render(request, 'circulars/generator.html', context)


def _generate_body_content(template_str, template_type, **kwargs):
    """Generate only the body content for the circular (no header/signature — those are in the template image)"""
    circular_no = get_next_circular_number()
    current_date = timezone.now().strftime("%d.%m.%Y")
    
    all_params = {
        'copy_to': COPY_TO_BLOCK,
        'circular_no': circular_no,
        'date': current_date,
        'occasion': kwargs.get('occasion', '[Enter Occasion]'),
        'holiday_date': kwargs.get('holiday_date', '[Enter Date]'),
        'exam_type': '[Semester/Internal/Model]',
        'academic_year': _academic_year(),
        'start_date': '[Start Date]',
        'end_date': '[End Date]',
        'meeting_type': '[Staff/Department/Emergency]',
        'recipients': 'Faculty Members and Staff',
        'meeting_date': '[Meeting Date]',
        'meeting_time': '[Meeting Time]',
        'venue': '[Venue]',
        'agenda': '    1. [Agenda Item 1]\n    2. [Agenda Item 2]\n    3. [Agenda Item 3]',
        'content': '[Enter your announcement content here]',
        'event_name': '[Event Name]',
        'event_date': '[Event Date]',
        'event_time': '[Event Time]',
        'event_description': '[Event Description]',
        'contact': '[Contact Person / Department]',
    }
    
    return template_str.format(**all_params).strip()


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
    
    active_template = CircularTemplate.get_active_template(request.user)
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
        'active_template': active_template,
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
    """AJAX endpoint for AI content generation using Ollama Llama model"""
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

    circular_no = get_next_circular_number()
    current_date = timezone.now().strftime("%d.%m.%Y")   # Real SIET date format

    # ── Get past circulars for context ───────────────────────────────
    past_circulars = Circular.objects.filter(
        user__email__in=['principal@siet.ac.in', 'admin@siet.ac.in']  # Only official circulars
    ).order_by('-created_at')[:10]  # Get last 10 circulars

    past_examples = ""
    if past_circulars.exists():
        past_examples = "\n\nPAST SIET CIRCULAR EXAMPLES (for reference):\n"
        for i, circ in enumerate(past_circulars, 1):
            past_examples += f"\n--- EXAMPLE {i}: {circ.title} ---\n{circ.content[:500]}...\n"
        past_examples += "\n"
    else:
        # If no past circulars, provide enhanced learning context
        past_examples = "\n\nLEARNING CONTEXT - STUDY THESE PATTERNS:\n" \
                       "- Holiday circulars: Always specify exact dates, mention hostel mess closure, end with well-wishes\n" \
                       "- Exam circulars: Include reporting time (15 min early), ID requirements, no electronic devices\n" \
                       "- Event circulars: Use indented key-value format for date/time/venue, then description\n" \
                       "- Disciplinary: Firm tone, clear consequences, end with cooperation request\n\n"

    # ── System prompt: teach the model the exact SIET format ──────────────
    system_prompt = (
        "You are a professional circular drafting assistant for Sri Shakthi Institute of Engineering and Technology (SIET), "
        "Coimbatore. You draft official circulars exactly in the format used by the Principal's office.\n\n"
        "STRICT FORMAT RULES:\n"
        "1. Do NOT include any letterhead, college name, Ref number, date, or signature block — those are added automatically.\n"
        "2. On the FIRST line, output ONLY a short title for internal reference, prefixed with 'Title:'. Example: 'Title: Holiday Declaration – Deepavali'\n"
        "3. Leave a blank line after the Title line.\n"
        "4. Do NOT write a 'Subject:' line. Real SIET circulars do not have Subject lines — the body starts directly.\n"
        "5. Write the body in concise, formal paragraphs. No 'Dear All' or salutation — go straight into the content.\n"
        "6. For holidays: you MUST use the REAL, EXACT calendar date of the festival/holiday for the current year "
        f"({timezone.now().year}). NEVER use placeholder text like '[Enter Date]' or '[Date]'. "
        "State the holiday period with exact dates, the occasion, mention Mess closure, and end with well-wishes.\n"
        "7. For exams: state period, instructions (carry ID, report 15 min early, no electronic devices, no malpractice).\n"
        "8. For meetings: state date, time, venue, agenda items in an indented key-value layout.\n"
        "9. For disciplinary notices: firmly state the issue, warning, and consequences.\n"
        "10. For events: state event name, date, time, venue in an indented key-value layout, then a brief description.\n"
        "11. End the body with a brief closing sentence (e.g., 'We wish you all a happy celebration.' or similar).\n"
        "12. Do NOT write 'PRINCIPAL' or any signature — it is added automatically.\n"
        "13. Do NOT write 'Copy to:' or any distribution list — it is added automatically.\n"
        "14. Use plain text only. No markdown, no bold (**), no bullet symbols like •. Use numbered lists (1. 2. 3.) if needed.\n"
        "15. Maximum 200 words. Keep it concise as real SIET circulars are brief and to the point.\n"
        "16. Match the tone of real SIET circulars — formal, direct, authoritative. Use phrases like 'We are pleased to inform you...', "
        "'This is to inform all students...', 'All are cordially invited...'.\n\n"
        f"{past_examples}"
        "REAL SIET CIRCULAR BODY EXAMPLES (these do NOT have Subject lines):\n\n"
        "--- HOLIDAY EXAMPLE ---\n"
        "Title: Holiday Declaration – Deepavali\n\n"
        "We are pleased to inform you that our Institute will observe a holiday from October 31, 2024 to "
        "November 03, 2024 in celebration of Deepavali. Please note that the Mess will be closed during this holiday period.\n\n"
        "Regular Classes and activities will resume on November 04, 2024, Monday.\n\n"
        "We wish you and your family a joyous and prosperous Deepavali. "
        "May this festive season bring light, happiness, and success in all your endeavors.\n\n"
        "--- DISCIPLINARY EXAMPLE ---\n"
        "Title: Lab Uniform – Strict Compliance\n\n"
        "This circular is to remind all students about the importance of adhering to the Lab Uniform dress code during "
        "their lab hours. It is mandatory for all students to wear their uniforms during laboratory sessions.\n\n"
        "It has been noticed that a few students did not wear Lab Uniform during their Lab Hours. "
        "Students are not allowed to change their uniforms inside the restrooms.\n\n"
        "Students who do not comply with the uniform policy will be subject to disciplinary action. "
        "Your cooperation is appreciated.\n\n"
        "--- GENERAL EXAMPLE ---\n"
        "Title: Commencement of Second Semester – B.E./B.Tech. 2024-28\n\n"
        "This is to inform all First Year Students that the Second Semester of the Undergraduate B.E./B.Tech. "
        "Programmes will begin on February 10, 2028. Students are advised to attend their regular classes from the "
        "first day of the semester, as attendance is mandatory.\n\n"
        "Further, all students must ensure that any pending "
        "fee formalities are completed before the semester begins. We wish all students a successful and productive semester ahead."
    )
    
    user_message = (
        f"Draft the body of an official SIET circular for the following request:\n\n"
        f"\"{prompt}\"\n\n"
        f"Remember: output ONLY the Title line + body paragraphs. No Subject line, no letterhead, no Ref, no date, no PRINCIPAL signature, no Copy to."
    )
    
    try:
        ai_body = call_llm_chat(
            user_message=user_message,
            system_prompt=system_prompt,
            model=LIGHT_MODEL,
            temperature=0.6,
            max_tokens=600,
            timeout=120,
        )
        # Strip any accidental markdown bold markers
        ai_body = ai_body.replace('**', '').replace('__', '')
        
        if not ai_body:
            return JsonResponse({'error': 'AI model returned empty response. Please try again.'}, status=500)
        
        # Extract title from "Title:" line and remove it from the body
        title = ""
        body_lines = ai_body.split('\n')
        body_start = 0
        for i, line in enumerate(body_lines):
            stripped = line.strip()
            if stripped.lower().startswith('title:'):
                title = stripped.split(':', 1)[1].strip().strip('\u2013\u2014-').strip()
                body_start = i + 1
                break
            elif stripped.lower().startswith('subject:'):
                # Fallback: AI may still output Subject: despite instructions
                title = stripped.split(':', 1)[1].strip().strip('\u2013\u2014-').strip()
                body_start = i + 1
                break
        
        # Remove the title/subject line and any leading blank lines from body
        ai_body_clean = '\n'.join(body_lines[body_start:]).strip()
        
        # Also strip any trailing "Copy to:" or "PRINCIPAL" the AI may have added
        clean_lines = ai_body_clean.split('\n')
        end_idx = len(clean_lines)
        for i in range(len(clean_lines) - 1, -1, -1):
            s = clean_lines[i].strip()
            if s in ('PRINCIPAL', 'Copy to:', '') or s.startswith('\u2022'):
                end_idx = i
            else:
                break
        ai_body_clean = '\n'.join(clean_lines[:end_idx]).strip()
        
        # ── Compose circular content (header/signature are in the template image) ──
        user_has_template = CircularTemplate.get_active_template(request.user) is not None
        
        # Generate subject line from title if available
        subject_line = ""
        if not title:
            title = prompt.strip()[:77] + ("..." if len(prompt) > 77 else "")
        elif len(title) > 80:
            title = title[:77] + "..."
        
        # Create subject line with title (will be made bold by rendering function)
        if title:
            subject_line = f"Subject: {title}\n"
        
        if user_has_template:
            generated_content = (
                f"Ref : {circular_no}                                         {current_date}\n\n"
                f"                                    CIRCULAR\n\n"
                f"{subject_line}\n"
                f"{ai_body_clean}\n\n"
                f"{COPY_TO_BLOCK}"
            )
        else:
            generated_content = (
                f"{INSTITUTION_HEADER}\n\n"
                f"Dr. N. K. Sakthivel, M.Tech., Ph.D.\n"
                f"Principal\n\n"
                f"Ref : {circular_no}                                         {current_date}\n\n"
                f"                                    CIRCULAR\n\n"
                f"{subject_line}\n"
                f"{ai_body_clean}\n\n"
                f"                                                                PRINCIPAL\n\n"
                f"{COPY_TO_BLOCK}"
            )
        
        return JsonResponse({
            'success': True,
            'content': generated_content,
            'title': title
        })
        
    except LLMError as e:
        logger.error("LLM call failed: %s", str(e))
        err = str(e)
        if 'ConnectionError' in err or 'Connection refused' in err:
            return JsonResponse({
                'error': 'Cannot connect to Ollama server. Please ensure Ollama is running.'
            }, status=503)
        if 'Timeout' in err or 'timed out' in err:
            return JsonResponse({
                'error': 'AI generation timed out. Please try a simpler prompt or try again later.'
            }, status=504)
        return JsonResponse({'error': f'AI service error: {err}'}, status=500)
    except Exception as e:
        logger.error("Unexpected error in AI generation: %s", str(e))
        return JsonResponse({
            'error': 'An unexpected error occurred. Please try again.'
        }, status=500)