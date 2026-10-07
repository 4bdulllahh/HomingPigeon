"""The example subjects, messages and signature, in every app language.

Never filled in on their own: the app starts blank and these only appear when
the user presses "Show me an example" (or saves a blank sheet to fill in).

They are written to land in the main inbox rather than Gmail's Promotions tab,
because that is what a first email needs. That means they read like one person
writing to another:
  * a greeting by name, and short plain paragraphs;
  * no links, pictures, bold text or bullet points;
  * no sales words (offer, free, discount, deal, order...);
  * 50 to 130 words, ending with one simple question to reply to.

``tests/test_core.py`` scores every language with the real scorer, so check
there after editing. Everything in [square brackets] is for the user to replace.
Spintax ({a|b}) and merge tags ({{Company}}) are kept as they are in every
language.
"""
from __future__ import annotations

from app import i18n

EXAMPLES: dict[str, dict] = {
    "en": {
        "subjects": [
            "{Quick question|A question} about {{Company}}",
            "{{FirstName}}, {a quick question|one question} for you",
            "{An idea|A thought} for the team at {{Company}}",
            "Is {{Company}} {looking at|thinking about} new suppliers this year?",
        ],
        "bodies": [
            "\n\n".join([
                "{Hi|Hello} {{FirstName}},",
                "I came across {{Company}} {while reading about|when I was looking at} "
                "businesses in [your region], and I wanted to get in touch {personally|directly}.",
                "My name is [Your Name] and I run [Your Company]. We help companies like yours "
                "with [what you do, in a few words], and most of the people we work with came "
                "to us because [the problem you solve].",
                "I will keep it short: would a ten minute call next week be useful, to see "
                "whether this is a fit for {{Company}}?",
                "{Thanks|Many thanks},",
            ]),
            "\n\n".join([
                "{Hi|Hello} {{FirstName}},",
                "I hope you do not mind me writing to you directly. I work at [Your Company], "
                "where we [what you do, in a few words] for businesses like {{Company}}.",
                "A {company|business} similar to yours told us recently that [a problem your "
                "customers often have] was taking far more of their time than it should. We "
                "{sorted that out|fixed that} for them within a few weeks.",
                "Is that something you run into at {{Company}} as well? If it is, I would be "
                "glad to share how we went about it.",
                "{Best wishes|Kind regards},",
            ]),
            "\n\n".join([
                "{Hi|Hello} {{FirstName}},",
                "{I will keep this brief|Just a short note}. I am [Your Name] from [Your "
                "Company], and we work with [type of business] on [what you do, in a few words].",
                "I noticed {{Company}} and thought there could be a good fit, but I would "
                "rather ask than guess. Who is the best person to talk to about [your area], "
                "and is that you?",
                "If the timing is wrong, that is no problem at all. Just let me know.",
                "{Thanks|Many thanks},",
            ]),
        ],
        "signature": "\n".join([
            "[Your Name]",
            "[Your job title], [Your Company]",
            "Phone: +000 0 000 0000",
            "[Street address, city, country]",
        ]),
    },
    "ar": {
        "subjects": [
            "{سؤال سريع|سؤال قصير} بخصوص {{Company}}",
            "{{FirstName}}، {سؤال سريع|سؤال واحد} لكم",
            "{فكرة|اقتراح} لفريق {{Company}}",
            "هل تبحث {{Company}} عن موردين جدد هذا العام؟",
        ],
        "bodies": [
            "\n\n".join([
                "{مرحبًا|أهلًا} {{FirstName}}،",
                "تعرّفت على {{Company}} {أثناء اطلاعي على|خلال بحثي عن} الشركات في [منطقتك]، "
                "وأردت التواصل معكم {شخصيًا|مباشرة}.",
                "اسمي [اسمك] وأدير [اسم شركتك]. نساعد شركات مثل شركتكم في [ما تقدمه في كلمات "
                "قليلة]، ومعظم من نعمل معهم جاؤوا إلينا لأن [المشكلة التي تحلها].",
                "سأختصر: هل تفيدكم مكالمة قصيرة مدتها عشر دقائق الأسبوع القادم، لنرى إن كان هذا "
                "مناسبًا لـ {{Company}}؟",
                "{مع الشكر|مع جزيل الشكر}،",
            ]),
            "\n\n".join([
                "{مرحبًا|أهلًا} {{FirstName}}،",
                "أرجو ألا تمانعوا في مراسلتي لكم مباشرة. أعمل في [اسم شركتك]، حيث نقدم [ما "
                "تقدمه في كلمات قليلة] لشركات مثل {{Company}}.",
                "أخبرتنا {شركة|مؤسسة} تشبه شركتكم مؤخرًا أن [مشكلة يواجهها عملاؤك كثيرًا] كانت "
                "تأخذ من وقتهم أكثر بكثير مما ينبغي، {وقد حللنا ذلك|وعالجنا ذلك} لهم خلال أسابيع "
                "قليلة.",
                "هل تواجهون الأمر نفسه في {{Company}}؟ إن كان كذلك، يسعدني أن أشارككم كيف "
                "تعاملنا معه.",
                "{مع أطيب التحيات|مع خالص التحية}،",
            ]),
            "\n\n".join([
                "{مرحبًا|أهلًا} {{FirstName}}،",
                "{سأكون مختصرًا|رسالة قصيرة مني}. أنا [اسمك] من [اسم شركتك]، ونعمل مع [نوع "
                "الشركات] في [ما تقدمه في كلمات قليلة].",
                "لفتت {{Company}} انتباهي وأعتقد أن هناك فرصة للتعاون، لكنني أفضل أن أسأل بدل "
                "أن أخمّن. من هو الشخص المناسب للحديث معه بخصوص [مجالك]، وهل هو أنتم؟",
                "إن لم يكن الوقت مناسبًا فلا مشكلة إطلاقًا، فقط أخبروني.",
                "{مع الشكر|مع جزيل الشكر}،",
            ]),
        ],
        "signature": "\n".join([
            "[اسمك]",
            "[مسماك الوظيفي]، [اسم شركتك]",
            "الهاتف: +000 0 000 0000",
            "[العنوان، المدينة، الدولة]",
        ]),
    },
    "de": {
        "subjects": [
            "{Kurze Frage|Eine Frage} zu {{Company}}",
            "{{FirstName}}, {eine kurze Frage|eine Frage} an Sie",
            "{Eine Idee|Ein Gedanke} für das Team von {{Company}}",
            "Sucht {{Company}} dieses Jahr neue Lieferanten?",
        ],
        "bodies": [
            "\n\n".join([
                "{Hallo|Guten Tag} {{FirstName}},",
                "ich bin auf {{Company}} gestoßen, {als ich mir Unternehmen in|während ich mich "
                "über Firmen in} [Ihrer Region] {angesehen habe|informiert habe}, und wollte "
                "mich {persönlich|direkt} bei Ihnen melden.",
                "Mein Name ist [Ihr Name] und ich leite [Ihr Unternehmen]. Wir unterstützen "
                "Firmen wie Ihre bei [was Sie tun, in wenigen Worten], und die meisten unserer "
                "Kunden kamen zu uns, weil [das Problem, das Sie lösen].",
                "Ich fasse mich kurz: Wäre ein zehnminütiges Gespräch nächste Woche hilfreich, "
                "um zu sehen, ob das für {{Company}} passt?",
                "{Viele Grüße|Beste Grüße}",
            ]),
            "\n\n".join([
                "{Hallo|Guten Tag} {{FirstName}},",
                "ich hoffe, es ist in Ordnung, dass ich Ihnen direkt schreibe. Ich arbeite bei "
                "[Ihr Unternehmen], wo wir [was Sie tun, in wenigen Worten] für Firmen wie "
                "{{Company}} übernehmen.",
                "Ein {Unternehmen|Betrieb} ähnlich wie Ihres hat uns kürzlich erzählt, dass "
                "[ein häufiges Problem Ihrer Kunden] viel mehr Zeit gekostet hat als nötig. Wir "
                "haben das innerhalb weniger Wochen {gelöst|in den Griff bekommen}.",
                "Kennen Sie das bei {{Company}} auch? Falls ja, erzähle ich Ihnen gern, wie wir "
                "dabei vorgegangen sind.",
                "{Viele Grüße|Freundliche Grüße}",
            ]),
            "\n\n".join([
                "{Hallo|Guten Tag} {{FirstName}},",
                "{ich fasse mich kurz|nur eine kurze Nachricht}. Ich bin [Ihr Name] von [Ihr "
                "Unternehmen], und wir arbeiten mit [Art von Unternehmen] an [was Sie tun, in "
                "wenigen Worten].",
                "{{Company}} ist mir aufgefallen und ich glaube, das könnte gut passen, aber ich "
                "frage lieber, als zu raten. Wer ist bei Ihnen der richtige Ansprechpartner für "
                "[Ihren Bereich], und sind Sie das vielleicht selbst?",
                "Wenn der Zeitpunkt gerade nicht passt, ist das überhaupt kein Problem. Geben "
                "Sie mir einfach kurz Bescheid.",
                "{Viele Grüße|Beste Grüße}",
            ]),
        ],
        "signature": "\n".join([
            "[Ihr Name]",
            "[Ihre Position], [Ihr Unternehmen]",
            "Telefon: +000 0 000 0000",
            "[Straße, Ort, Land]",
        ]),
    },
    "es": {
        "subjects": [
            "{Una pregunta rápida|Una pregunta} sobre {{Company}}",
            "{{FirstName}}, {una pregunta rápida|una pregunta} para usted",
            "{Una idea|Una sugerencia} para el equipo de {{Company}}",
            "¿Busca {{Company}} nuevos proveedores este año?",
        ],
        "bodies": [
            "\n\n".join([
                "{Hola|Buenos días} {{FirstName}}:",
                "Encontré {{Company}} {mientras leía sobre|al buscar} empresas en [su región] "
                "y quise ponerme en contacto con usted {personalmente|directamente}.",
                "Me llamo [Su nombre] y dirijo [Su empresa]. Ayudamos a empresas como la suya "
                "con [lo que hace, en pocas palabras], y la mayoría de nuestros clientes "
                "llegaron a nosotros porque [el problema que resuelve].",
                "Seré breve: ¿le resultaría útil una llamada de diez minutos la próxima semana "
                "para ver si encaja con {{Company}}?",
                "{Gracias|Muchas gracias},",
            ]),
            "\n\n".join([
                "{Hola|Buenos días} {{FirstName}}:",
                "Espero que no le moleste que le escriba directamente. Trabajo en [Su empresa], "
                "donde nos ocupamos de [lo que hace, en pocas palabras] para empresas como "
                "{{Company}}.",
                "Hace poco, una {empresa|compañía} parecida a la suya nos contó que [un problema "
                "habitual de sus clientes] le quitaba mucho más tiempo del necesario. Lo "
                "{resolvimos|solucionamos} en pocas semanas.",
                "¿Les pasa algo parecido en {{Company}}? Si es así, con gusto le cuento cómo lo "
                "abordamos.",
                "{Un saludo|Saludos cordiales},",
            ]),
            "\n\n".join([
                "{Hola|Buenos días} {{FirstName}}:",
                "{Seré breve|Solo una nota corta}. Soy [Su nombre], de [Su empresa], y "
                "trabajamos con [tipo de empresa] en [lo que hace, en pocas palabras].",
                "Me fijé en {{Company}} y creo que podría haber una buena relación, pero "
                "prefiero preguntar antes que suponer. ¿Quién es la persona adecuada para hablar "
                "de [su área]? ¿Es usted?",
                "Si no es buen momento, no pasa nada. Solo dígamelo.",
                "{Gracias|Muchas gracias},",
            ]),
        ],
        "signature": "\n".join([
            "[Su nombre]",
            "[Su cargo], [Su empresa]",
            "Teléfono: +000 0 000 0000",
            "[Dirección, ciudad, país]",
        ]),
    },
    "fr": {
        "subjects": [
            "{Petite question|Une question} au sujet de {{Company}}",
            "{{FirstName}}, {une petite question|une question} pour vous",
            "{Une idée|Une suggestion} pour l'équipe de {{Company}}",
            "{{Company}} cherche-t-elle de nouveaux fournisseurs cette année ?",
        ],
        "bodies": [
            "\n\n".join([
                "{Bonjour|Bonjour à vous} {{FirstName}},",
                "J'ai découvert {{Company}} {en m'intéressant aux|en regardant les} entreprises "
                "de [votre région], et je voulais vous écrire {personnellement|directement}.",
                "Je m'appelle [Votre nom] et je dirige [Votre entreprise]. Nous aidons des "
                "entreprises comme la vôtre à [ce que vous faites, en quelques mots], et la "
                "plupart de nos clients sont venus vers nous parce que [le problème que vous "
                "résolvez].",
                "Je serai bref : un appel de dix minutes la semaine prochaine vous serait-il "
                "utile, pour voir si cela convient à {{Company}} ?",
                "{Merci|Merci beaucoup},",
            ]),
            "\n\n".join([
                "{Bonjour|Bonjour à vous} {{FirstName}},",
                "J'espère que vous ne m'en voudrez pas de vous écrire directement. Je travaille "
                "chez [Votre entreprise], où nous nous occupons de [ce que vous faites, en "
                "quelques mots] pour des entreprises comme {{Company}}.",
                "Une {entreprise|société} proche de la vôtre nous a récemment expliqué que [un "
                "problème fréquent chez vos clients] lui prenait bien plus de temps que prévu. "
                "Nous avons {réglé|résolu} cela en quelques semaines.",
                "Est-ce quelque chose que vous rencontrez aussi chez {{Company}} ? Si oui, je "
                "vous expliquerai volontiers comment nous nous y sommes pris.",
                "{Bien à vous|Cordialement},",
            ]),
            "\n\n".join([
                "{Bonjour|Bonjour à vous} {{FirstName}},",
                "{Je serai bref|Juste un petit mot}. Je suis [Votre nom], de [Votre "
                "entreprise], et nous travaillons avec [type d'entreprise] sur [ce que vous "
                "faites, en quelques mots].",
                "{{Company}} a retenu mon attention et je pense qu'il pourrait y avoir un "
                "intérêt commun, mais je préfère demander plutôt que supposer. Qui est la bonne "
                "personne pour parler de [votre domaine], et est-ce vous ?",
                "Si le moment n'est pas le bon, aucun souci. Dites-le-moi simplement.",
                "{Merci|Merci beaucoup},",
            ]),
        ],
        "signature": "\n".join([
            "[Votre nom]",
            "[Votre poste], [Votre entreprise]",
            "Téléphone : +000 0 000 0000",
            "[Adresse, ville, pays]",
        ]),
    },
}


def for_language(code: str | None = None) -> dict:
    """The examples in ``code`` (default: the app's language), falling back to English."""
    return EXAMPLES.get(code or i18n.language(), EXAMPLES["en"])
