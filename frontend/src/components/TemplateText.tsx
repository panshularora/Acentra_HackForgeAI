import { MaskedText } from './MaskedText';

/** Drain3 marks the variable parts of a log template as `<*>`. */
const WILDCARD_SPLIT = /(<\*>)/;
const WILDCARD = '<*>';

/** Renders a log template with its wildcards and any masked-PII placeholders set apart. */
export function TemplateText({ text }: { text: string }) {
  return (
    <>
      {text.split(WILDCARD_SPLIT).map((part, i) =>
        part === WILDCARD ? (
          <span key={i} className="template-wildcard">
            {part}
          </span>
        ) : (
          <MaskedText key={i} text={part} />
        ),
      )}
    </>
  );
}
