using Microsoft.AspNetCore.Http;
using SmartSecuritySystem.Models;
using System;
using System.Collections.Generic;
using System.Linq;
using WebApp.Models; // unified namespace

namespace WebApp.Services
{
    public class AuthService
    {
        // 🔹 In-memory users (temporary for testing)
        private readonly List<User> _users;

        public AuthService()
        {
            _users = new List<User>
            {
                new User
                {
                    Id = 1,
                    Username = "admin",
                    PasswordHash = "1234", // ⚠️ plain text for dev only
                    Role = "Admin",
                    Name = "System Administrator",
                    Email = "admin@email.com",
                    Status = "Active"
                },
                new User
                {
                    Id = 2,
                    Username = "security",
                    PasswordHash = "1234",
                    Role = "Security",
                    Name = "Security Personnel",
                    Email = "security@email.com",
                    Status = "Active"
                }
            };
        }

        // =========================
        // VALIDATE LOGIN
        // =========================
        public (bool success, User? user) ValidateUser(string username, string password)
        {
            if (string.IsNullOrWhiteSpace(username) || string.IsNullOrWhiteSpace(password))
                return (false, null);

            var user = _users.FirstOrDefault(u =>
                u.Username.Equals(username, StringComparison.OrdinalIgnoreCase));

            if (user == null || !VerifyPassword(user, password))
                return (false, null);

            return (true, user);
        }

        // =========================
        // GET CURRENT USER FROM SESSION
        // =========================
        public User? GetCurrentUser(HttpContext context)
        {
            int? userId = context.Session.GetInt32("UserId");
            if (userId == null) return null;

            return _users.FirstOrDefault(u => u.Id == userId.Value);
        }

        // =========================
        // VERIFY PASSWORD (private)
        // =========================
        public bool VerifyPassword(User? user, string password)
        {
            if (user == null) return false;
            return user.PasswordHash == password; // ⚠️ plain text, dev only
        }

        // =========================
        // UPDATE PASSWORD
        // =========================
        public bool UpdatePassword(int userId, string newPassword)
        {
            var user = _users.FirstOrDefault(u => u.Id == userId);
            if (user == null) return false;

            user.PasswordHash = newPassword;
            return true;
        }

        // =========================
        // CHECK IF EMAIL EXISTS
        // =========================
        public bool EmailExists(string email)
        {
            if (string.IsNullOrWhiteSpace(email)) return false;

            return _users.Any(u =>
                u.Email.Equals(email, StringComparison.OrdinalIgnoreCase));
        }

        // =========================
        // GENERATE RESET TOKEN
        // =========================
        public string GenerateResetToken()
        {
            return Guid.NewGuid().ToString();
        }

        // =========================
        // RESET PASSWORD (TEMP)
        // =========================
        public bool ResetPassword(string token, string newPassword)
        {
            // 🔹 TEMP: always resets admin for testing
            var user = _users.FirstOrDefault(u => u.Username == "admin");
            if (user == null) return false;

            user.PasswordHash = newPassword;
            return true;
        }
    }
}