// Client-side Sensitive Data Masking for Privacy and Safety

export function maskSensitiveData(text: string): string {
  if (!text) return "";

  let masked = text;

  // 1. Mask 12-digit Aadhaar numbers (e.g., 1234 5678 9012 or 123456789012)
  masked = masked.replace(/\b(\d{4})[\s-](\d{4})[\s-](\d{4})\b/g, "XXXX-XXXX-$3");
  masked = masked.replace(/\b(\d{8})(\d{4})\b/g, "XXXXXXXX$2");

  // 2. Mask 10-character PAN numbers (e.g., ABCDE1234F -> ABCDE****F)
  masked = masked.replace(/\b([A-Z]{5})(\d{4})([A-Z])\b/g, "$1****$3");

  // 3. Mask 13-19 digit card numbers (keep last 4 digits)
  masked = masked.replace(/\b(?:\d{4}[ -]?){3}\d{1,4}\b/g, (match) => {
    const digits = match.replace(/[\s-]/g, "");
    if (digits.length >= 13 && digits.length <= 19) {
      const last4 = digits.slice(-4);
      return `****-****-****-${last4}`;
    }
    return match;
  });

  // 4. Mask anything after password/pwd/passcode/otp/secret
  masked = masked.replace(
    /\b(password|pwd|passcode|otp|secret|pin)[\s:=]+([^\s,;]+)/gi,
    "$1: [MASKED]"
  );

  return masked;
}
