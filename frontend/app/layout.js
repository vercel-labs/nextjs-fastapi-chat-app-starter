import "./globals.css";

export const metadata = {
  title: "Chat",
  description: "Minimal chat app.",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
