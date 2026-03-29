using Microsoft.AspNetCore.Mvc;
using System.Security.Claims;
using Microsoft.AspNetCore.Authentication;
using Microsoft.AspNetCore.Authentication.Cookies;

namespace SmartSecuritySystem.Controllers
{
    public class AuthController : Controller
    {
        // =========================
        // GET: LOGIN
        // =========================
        public IActionResult Login()
        {
            return View();
        }

        // =========================
        // POST: LOGIN
        // =========================
        [HttpPost]
        public async Task<IActionResult> Login(string username, string password, bool rememberMe)
        {
            string role = null;

            // 🔥 TEMP USERS (Replace with DB)
            if (username == "admin" && password == "1234")
                role = "Admin";
            else if (username == "security" && password == "1234")
                role = "Security";

            if (role != null)
            {
                var claims = new List<Claim>
                {
                    new Claim(ClaimTypes.Name, username),
                    new Claim(ClaimTypes.Role, role)
                };

                var identity = new ClaimsIdentity(
                    claims,
                    CookieAuthenticationDefaults.AuthenticationScheme);

                var principal = new ClaimsPrincipal(identity);

                var authProperties = new AuthenticationProperties
                {
                    IsPersistent = rememberMe,
                    ExpiresUtc = rememberMe
                        ? DateTime.UtcNow.AddDays(7)
                        : DateTime.UtcNow.AddHours(1)
                };

                await HttpContext.SignInAsync(
                    CookieAuthenticationDefaults.AuthenticationScheme,
                    principal,
                    authProperties);

                // 🔁 REDIRECT BASED ON ROLE
                if (role == "Admin")
                    return RedirectToAction("Index", "Admin");
                else
                    return RedirectToAction("Index", "Dashboard");
            }

            ViewBag.Error = "Invalid username or password";
            return View();
        }

        // =========================
        // LOGOUT
        // =========================
        public async Task<IActionResult> Logout()
        {
            await HttpContext.SignOutAsync();
            return RedirectToAction("Login");
        }

        // =========================
        // GET: FORGOT PASSWORD
        // =========================
        [HttpGet]
        public IActionResult ForgotPassword()
        {
            return View();
        }

        // =========================
        // POST: FORGOT PASSWORD
        // =========================
        [HttpPost]
        public IActionResult ForgotPassword(string email)
        {
            if (string.IsNullOrEmpty(email))
            {
                ViewBag.Error = "Email is required";
                return View();
            }

            // 🔥 TEMP USER CHECK (Replace with DB)
            if (email == "admin@email.com")
            {
                // 🔐 GENERATE TOKEN
                var token = Guid.NewGuid().ToString();

                // 👉 In real system:
                // Save token to DB with expiry + user

                // 🔗 CREATE RESET LINK
                var resetLink = Url.Action(
                    "ResetPassword",
                    "Auth",
                    new { token = token },
                    Request.Scheme);

                // 👉 SEND EMAIL HERE (later)
                Console.WriteLine("RESET LINK: " + resetLink);

                ViewBag.Message = "Password reset link has been sent to your email.";
            }
            else
            {
                ViewBag.Error = "Email not found";
            }

            return View();
        }

        // =========================
        // GET: RESET PASSWORD
        // =========================
        [HttpGet]
        public IActionResult ResetPassword(string token)
        {
            if (string.IsNullOrEmpty(token))
            {
                return RedirectToAction("Login");
            }

            // 👉 In real system:
            // Validate token from DB

            ViewBag.Token = token;
            return View();
        }

        // =========================
        // POST: RESET PASSWORD
        // =========================
        [HttpPost]
        public IActionResult ResetPassword(string token, string newPassword)
        {
            if (string.IsNullOrEmpty(token) || string.IsNullOrEmpty(newPassword))
            {
                ViewBag.Error = "Invalid request";
                return View();
            }

            // 👉 In real system:
            // 1. Validate token
            // 2. Get user
            // 3. Hash password
            // 4. Save to DB
            // 5. Delete token

            ViewBag.Message = "Password successfully reset!";
            return View();
        }
    }
}